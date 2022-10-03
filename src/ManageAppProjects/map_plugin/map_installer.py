# coding: utf-8
""" Модуль плагина для управления прикладными проектами  """
import pathlib
from pprint import pprint, pformat
from typing import Optional, Dict, Any, List, OrderedDict
import termcolor
import time
import shutil
from pathlib import PurePath, Path
import os
import sys
import json
from ruamel.yaml import CommentedMap, CommentedSeq

from fire.formatting import Bold

from components.base_component import BaseComponent
from components.component_manager import component
from py_common.logger import log
from common_plugin import yaml_tools
from sungero_deploy.all import All
from sungero_deploy.scripts_config import get_config_model
from sungero_deploy.tools.sungerodb import SungeroDB
from py_common import io_tools, process
from sungero_deploy.scripts_config import Config
from common_plugin import git_tools

if 'platform_plugin.sungero_tenants.dbtools' in sys.modules:
    from platform_plugin.sungero_tenants.dbtools import ENABLE_XP_CMDSHELL # 4.5
else:
    from sungero_tenants.dbtools import ENABLE_XP_CMDSHELL # 4.2-4.4
if 'platform_plugin.deployment_tool' in sys.modules:
    from platform_plugin.deployment_tool import DeploymentTool # 4.5
else:
    from sungero_deploy.deployment_tool import DeploymentTool # 4.2-4.4
if 'platform_plugin.static_controller' in sys.modules:
    from platform_plugin.static_controller import StaticController # 4.5
else:
    from sungero_deploy.static_controller import StaticController  # 4.2-4.4

MANAGE_APPLIED_PROJECTS_ALIAS = 'map'

#region service function

def _get_rx_version(need_short: bool = True) -> str:
    """Вернуть версию RX
    """
    # версия 4.2. Информация о билде прикладной хранится в version.txt
    version_dict = yaml_tools.load_yaml_from_file(_get_check_file_path("etc\\_builds\\version.txt"))
    applied_builds_version = version_dict["builds"].get("applied_builds", None)
    if applied_builds_version is not None:
        return applied_builds_version["version"]

    with open(_get_check_file_path("etc\\_builds\\DirectumRX\\manifest.json"),  'r', encoding='utf-8') as manifest_json:
        data = " ".join(manifest_json.readlines())
        manifest_dict = json.loads(data)
        return manifest_dict["version"]

def _copy_database_mssql(config: Config, src_db_name: str, dst_db_name: str) -> None:
    """Создать копию базы данных на Microsoft SQL Server.

    Args:
        config: конфиг Sungero.
        src_db_name: исходная БД.
        dst_db_name: целевая БД.
    """
    log.info(f'Create database backup: "{src_db_name}".')

    # найти каталог для резервных копий
    # в DirectumLauncher 4.4 изменилось имя функции, поэтому пробуем оба варианта
    database_folder = None
    try:
        # версия 4.4
        from sungero_tenants.dbtools import get_mssql_database_folder
        database_folder = get_mssql_database_folder(config, src_db_name)
    except:
        pass
    if database_folder is None:
        try:
            # до версии 4.4
            from sungero_tenants.dbtools import get_database_folder
            database_folder = get_database_folder(config, src_db_name)
        except:
            pass
    if database_folder is None:
        try:
            # версия 4.5
            from platform_plugin.sungero_tenants.dbtools import get_mssql_database_folder
            database_folder = get_mssql_database_folder(config, src_db_name)
        except:
            pass
    if database_folder is None:
        raise ValueError(f"Не удалось найти функцию для получения имени каталога резервных копий.")

    command_text = f"""
        -- ============ копипаста из dbtools.create_database_backup() ============
        declare @DatabaseName sysname = '{src_db_name}'
        declare @DatabaseFolder nvarchar(255) = '{database_folder}'

        -- Получить путь к последнему полному бэкапу базы.
        declare @FullBackupPath nvarchar(255) = ''
        set @FullBackupPath = @DatabaseFolder + @DatabaseName + '_' + replace(cast(newid() as varchar(36)), '-', '') + '.full'

        declare @BackupName nvarchar(255) = 'Backup created by tenant manage script'
        backup database @DatabaseName to disk = @FullBackupPath with copy_only, init, name = @BackupName
        if @@ERROR <> 0
        begin
          print(@FullBackupPath)
          return
        end
        print('!Создана полная резервная копия "' + @FullBackupPath + '"')
        select @FullBackupPath

        -- =========== копипаста из dbtools.create_database_from_backup() ============
        declare @NewDatabaseName sysname = '{dst_db_name}'

        print('!Создание из резервной копии: "' + @FullBackupPath + '"')
        -- Сформировать список файлов эталонной базы данных для запроса восстановления из бэкапа.
        declare @productver VARCHAR(50) = (SELECT CAST(SERVERPROPERTY('productversion') AS VARCHAR(50)))
        declare @version int = CAST(LEFT(@productver, CHARINDEX('.', @productver)-1) AS INT)

        create table #BackupFiles (LogicalName nvarchar(128), PhysicalName nvarchar(260), Type char(1), FileGroupName nvarchar(120),
            Size numeric(20, 0), MaxSize numeric(20, 0), FileID bigint, CreateLSN numeric(25,0), DropLSN numeric(25,0),
            UniqueID uniqueidentifier, ReadOnlyLSN numeric(25,0), ReadWriteLSN numeric(25,0), BackupSizeInBytes bigint,
            SourceBlockSize int, FileGroupID int, LogGroupGUID uniqueidentifier, DifferentialBaseLSN numeric(25,0),
            DifferentialBaseGUID uniqueidentifier, IsReadOnly bit, IsPresent bit, TDEThumbprint varbinary(32));
        -- С версии SQL2016 появилась новая колонка.
        if @version > 12
        begin
        alter table #BackupFiles
            add SnapshotUrl nvarchar(2083) NULL;
        end
        insert into #BackupFiles
        exec('restore filelistonly from disk = ''' + @FullBackupPath + '''')
        if @@ERROR <> 0
        return
        declare @MoveStatement nvarchar(4000) = ''
        select
        @MoveStatement = @MoveStatement + ', move ''' + LogicalName + ''' to ''' +
            @DatabaseFolder + @NewDatabaseName +
            case
            when Type = 'D' then '.mdf'
            when Type = 'L' then '_log.ldf'
            when Type = 'F' then '\FullTextData'
            end + ''''
        from
        #BackupFiles
        drop table #BackupFiles
        print(@MoveStatement)
        -- Восстановить новую базу из бэкапа эталонной.
        exec('restore database [' + @NewDatabaseName + '] from disk = ''' + @FullBackupPath + ''' with recovery, replace ' + @MoveStatement)
        if @@ERROR = 0
            print('!База данных "' + @NewDatabaseName + '" создана')

        -- Удалить созданную резервную копию
        declare @Command varchar(4000) = ''
        set @Command = 'del "' + @FullBackupPath + '"'
        exec master..xp_cmdshell @Command
        if @@ERROR = 0
            print('!Файл созданной резервной копии удален')
        """

    result = SungeroDB(config).execute_command(ENABLE_XP_CMDSHELL.format(command_text), return_results=True)
    log.info(f'Database copied: {result}')

def _copy_database_postgresql(src_sungero_config: Any, src_db_name: str, dst_db_name: str):
    """Создать копию базы данных на PostgreSQL.

    Args:
        config: конфиг Sungero в виде yaml.
        src_db_name: исходная БД.
        dst_db_name: целевая БД.
    """
    postgree_path = _get_map_settings(config=src_sungero_config, param_name="postgresql_bin", is_required=True)
    cmd = f'"{postgree_path}\\createdb.exe" -w {dst_db_name}'
    exit_code = process.try_execute(cmd, encoding='cp1251') #cp1251  utf-8
    if exit_code != 0:
        raise IOError(f'Ошибка при создании БД')
    cmd = f'"{postgree_path}\\pg_dump.exe" -h localhost -w {src_db_name} | "{postgree_path}\\psql" -q -h localhost -w {dst_db_name}'
    exit_code = process.try_execute(cmd, encoding='cp1251')
    if exit_code != 0:
        raise IOError(f'Ошибка при копировании данных БД')

def _colorize(x, color, attrs):
    return termcolor.colored(x, color=color, attrs=attrs)
def _colorize_green(x):
    return _colorize(x, color="green", attrs=["bold"])
def _colorize_red(x):
    return _colorize(x, color="red", attrs=["bold"])
def _colorize_cyan(x):
    return _colorize(x, color="cyan", attrs=["bold"])

def _get_url(config) -> None:
    """Вернуть  url для открытия веб-клиента текущего инстанса"""
    vars = config.variables
    srv_cfgs = config.services_config
    return f'{vars["protocol"]}://{vars["host_fqdn"]}:{vars["http_port"]}/{srv_cfgs["SungeroWebServer"]["WEB_HOST_PATH_BASE"]}/#'

def _show_config(config_path):
    config = yaml_tools.load_yaml_from_file(_get_check_file_path(config_path))
    vars = config.get("variables")
    repos = config.get("services_config").get("DevelopmentStudio").get('REPOSITORIES').get("repository")
    maxlen = 0
    for repo in repos:
        if maxlen < len(repo.get("@folderName")):
            maxlen = len(repo.get("@folderName"))
    log.info(Bold(f'Назначение:          {vars.get("purpose")}'))
    if vars.get("project_config_path") is not None:
        log.info(f'project_config_path: {_colorize_green(vars.get("project_config_path"))}')
    log.info(f'database:            {_colorize_green(vars.get("database"))}')
    log.info(f'home_path:           {_colorize_green(vars.get("home_path"))}')
    log.info(f'home_path_src:       {_colorize_green(vars.get("home_path_src"))}')
    log.info('repositories:')
    repos_str = []
    maxlen_folder = 0
    maxlen_status = 0
    for repo in repos:
        folder_str = f'folder: {_colorize_green(repo.get("@folderName")):}'
        solutiontype_str = f'solutiontype: {_colorize_green(repo.get("@solutionType"))}'
        url_str = f'url: {_colorize_green(repo.get("@url"))}'
        status_str = f'status: {repo_info(vars.get("home_path_src"), repo.get("@folderName"))}'
        repos_str.append({"folder": folder_str,
                          "solutiontype": solutiontype_str,
                          "url": url_str,
                          "status": status_str})
        maxlen_folder = len(folder_str) if maxlen_folder < len(folder_str) else maxlen_folder
        maxlen_status = len(status_str) if maxlen_status < len(status_str) else maxlen_status

    for repo_str in repos_str:
        log.info(f'  {repo_str["folder"].ljust(maxlen_folder)} {repo_str["status"].ljust(maxlen_status)} {repo_str["solutiontype"]} {repo_str["url"]}')

def _get_check_file_path(config_path: str) -> Path:
    if not config_path:
        raise ValueError("config_path does not set.")
    p_config_path = Path(config_path)
    if not p_config_path.is_file():
        log.error(f'Файл {config_path} не найден.')
        raise FileNotFoundError(f"'config_path' file not found: '{config_path}'")
    return p_config_path

def _get_full_path(root: str, relative: str) -> str:
    """Вычислить полный путь. Если параметр relative содержит абаслютный путь - то возвращает значение этого параметра.
    В противном случае возвращается root+relative.
    """
    if Path(relative).is_absolute():
        return str(relative)
    else:
        return str(PurePath(root, relative))

def _generate_empty_config_by_template(new_config_path: str, template_config: str) -> None:
    """ Создать новый файл конфига по шаблону """
    p_config_path = pathlib.Path(new_config_path)
    if not p_config_path.exists():
        with open(new_config_path, 'w', encoding='utf-8') as f:
            f.write(template_config)
        log.info(_colorize_green(f'Создан файл {new_config_path}.'))
    else:
        log.error(f'Файл {new_config_path} уже существует.')

def _update_sungero_config(project_config_path, sungero_config_path):
    """Преобразовать текущий config.yml в соотвтетствии с указанным конфигом проекта.
    Преобразование выполняется без сохранения на диске

    Args:
        * project_config_path - путь к конфигу проекта
        * sungero_config_path - путь к config.yml

    Return:
        * преоразованный конфиг
    """
    src_config = yaml_tools.load_yaml_from_file(project_config_path)
    dst_config = yaml_tools.load_yaml_from_file(sungero_config_path)
    dst_config["services_config"]["DevelopmentStudio"]['REPOSITORIES']["repository"]  = src_config["services_config"]["DevelopmentStudio"]['REPOSITORIES']["repository"].copy()
    dst_config["variables"]["purpose"] = src_config["variables"]["purpose"]
    dst_config["variables"]["database"] = src_config["variables"]["database"]
    dst_config["variables"]["home_path"] = src_config["variables"]["home_path"]
    dst_config["variables"]["home_path_src"]  = src_config["variables"]["home_path_src"]
    dst_config["variables"]["project_config_path"]  = project_config_path
    return dst_config

def _get_map_settings(config_path: str = None, config: Any = None, param_name: str = None, is_required: bool = False, default_value: Any = None) -> Any:
    """Получить значение параметра компоненты Manage Applied Projects из config.yml

    Args:
        config_path: str - путь к конфигу
        config: str - сам конфиг. config_path и config - взаимоисключающие параметры, config имеет приоритет
        param_name: str - имя параметра
        is_required: bool = False - если True, то при отсутствии параметра в config.yml будет выброшено исключение
        default_value: Any = None - значение по умолчанию. Если is_required=False и параметра нет в config.yml, то вернется default_value
    """
    if config is None:
        if config_path is not None:
            config = yaml_tools.load_yaml_from_file(_get_check_file_path(config_path)) #get_config_model(config_path)
        else:
            raise AssertionError('Должен быть либо указан параметр config, либо config_path')
    if "manage_applied_projects" in config:
        manage_applied_projects_config = config.get("manage_applied_projects", None)
        if param_name in manage_applied_projects_config:
            return manage_applied_projects_config.get(param_name)
        else:
            if is_required:
                raise AssertionError(f'В config.yml отсутствует параметр manage_applied_projects -> {param_name}')
            else:
                return default_value
    else:
        print(5)
        if is_required:
            raise AssertionError('В config.yml отсутствует раздел "manage_applied_projects"')
        else:
            return default_value

def _run_dds(config_path: str, need_run: bool, confirm: bool) -> None:
    """Запустить DDS, если попросили об этом (параметр need_run) или в конфиге настроен запуск по умолчанию.
    Если явно попросили запустить DDS, а он не установлен, то DDS не будет запущен, а в log выведется сообщение.
    Если параметр confirm установлен в True, то перед запуском DDS будет выведен запрос на подтверждение запуска.
    """
    if need_run or (need_run is None and _get_map_settings(config_path=config_path,
                                                            param_name="run_dds_after_set_project",
                                                            is_required=False, default_value=False)):
        if 'dds_plugin.development_studio' in sys.modules:
            from dds_plugin.development_studio import DevelopmentStudio
            while (True):
                answ = input("Запустить DDS? (y,n):") if confirm else 'y'
                if answ=='y' or answ=='Y':
                    DevelopmentStudio(config_path).run()
                    break
                elif answ=='n' or answ=='N':
                    break
        else:
            log.warning(f'Компонента Directum Development Studio не установлена.')


def repo_info(root_src, folder):
    path = str(PurePath(root_src, folder))

    if pathlib.Path(path).exists():
        stdout_messages: List[str] = ['']
        result = git_tools.git_run("branch --show-current", cwd=path, silent=True, log_stdout=False,
                        filter=process.save_stdout_message_handler(stdout_messages))
        if result == 0:
            branch = stdout_messages.pop()

            stdout_messages_f: List[str] = []
            result = git_tools.git_run("status -s",
                            cwd=path,
                            filter=process.save_stdout_message_handler(stdout_messages_f),
                            log_stdout=False)
            if result == 0:
                changes_dict = {}
                for m in stdout_messages_f:
                    t = m.split(" ")[0]
                    changes_dict[t] = changes_dict.get(t, 0)+1
                changes = ""
                for k,v in changes_dict.items():
                    if len(changes) == 0:
                        changes = f'{k}:{v}'
                    else:
                        changes = f'{changes}, {k}:{v}'
                return f'({_colorize_green(branch)}) {changes}'
    return f'{_colorize("no data", color="yellow", attrs=["bold"])}'

#endregion

@component(alias=MANAGE_APPLIED_PROJECTS_ALIAS)
class ManageAppliedProject(BaseComponent):
    """ Компонент Изменение проекта. """

    #region constructor-destructor
    def __init__(self, config_path: Optional[str] = None) -> None:
        """
        Конструктор.

        Args:
            config_path: Путь к конфигу.
        """
        super(self.__class__, self).__init__(config_path)
        self._static_controller = StaticController(self.config_path)

    def install(self) -> None:
        """
        Установить компоненту.
        """
        log.info(f'"{self.__class__.__name__}" component has been successfully installed.')
        self._print_help_after_action()

    def uninstall(self) -> None:
        """
        Удалить компоненту.
        """
        log.info(f'"{self.__class__.__name__}" component has been successfully uninstalled.')
        self._print_help_after_action()
    #endregion

    #region manage projects

    def update_config(self, template_config_path: str, confirm: bool = True):
        """ Изменить config.yml используя шаблон

        Args:
            template_config_path - путь к конфигу, из которого будут браться новые значения
            confirm: признак необходимости выводить запрос на создание проекта. По умолчанию - True
        """
        inst_path = Path(self.config_path).parent.parent
        log.info(f'Корневой каталог текущего инстанса: {str(inst_path)}')

        def _update_CommentedMap(template_config: CommentedMap, dst_config: CommentedMap):
            for k,v in template_config.items():
                if type(v) == CommentedMap:
                    if k in dst_config.keys():
                        if dst_config[k] is not None:
                            _update_CommentedMap(v, dst_config[k])
                        else:
                            dst_config[k] = v
                    else:
                        dst_config[k] = v
                        _update_CommentedMap(v, dst_config[k])
                elif type(v) == CommentedSeq:
                    if k in dst_config.keys():
                        dst_config[k] = v
                    else:
                        dst_config[k] = v
                        _update_CommentedMap(v, dst_config[k])
                else:
                    dst_config[k] = v

        def _show_CommentedMap(template_config: CommentedMap, dst_config: CommentedMap, indent: int = 1):
            indent_template = "  "
            mark = ""
            for k,v in template_config.items():
                if type(v) == CommentedMap:
                    dst_config_next_level = None
                    if dst_config is not None and k in dst_config.keys():
                        mark = ""
                        dst_config_next_level = dst_config[k]
                    else:
                        mark = _colorize_green('[+]')
                    log.info(f"{(indent)*indent_template}{mark}{k}:")
                    _show_CommentedMap(v, dst_config_next_level, (indent+1))
                elif type(v) == CommentedSeq:
                    if k.lower() == "repository":
                        maxlen = 0
                        for repo in v:
                            if maxlen < len(repo.get("@folderName")):
                                maxlen = len(repo.get("@folderName"))
                        for repo in v:
                            log.info(f'{(indent)*indent_template}{_colorize_cyan("[*]")}folder: {_colorize_green(repo.get("@folderName").ljust(maxlen)):} solutiontype: {_colorize_green(repo.get("@solutionType"))}  url: {_colorize_green(repo.get("@url"))}')
                    else:
                        for r in v:
                            log.info(f"{(indent)*indent_template}{r}")
                else:
                    if dst_config is not None and k in dst_config.keys():
                        if v == dst_config[k]:
                            mark = "[.]"
                            value = f"'{v}'"
                        else:
                            mark = _colorize_cyan('[*]')
                            value = f"'{dst_config[k]}' -> '{v}'"
                    else:
                        mark = _colorize_green('[+]')
                        value = f"'{v}'"
                    log.info(f"{(indent)*indent_template}{mark}{k}: {value}")

        log.info(f'Чтение исходного config.yml: {self.config_path}')
        dst_config = yaml_tools.load_yaml_from_file(self.config_path)
        log.info(f'Чтение файла с требуемыми параметрами: {template_config_path}')
        template_config = yaml_tools.load_yaml_from_file(_get_check_file_path(template_config_path))

        log.info(f'{_colorize_green("Предлагаемые изменения config.yml")}')
        log.info(f'Легенда изменений:')
        log.info(f'{_colorize_cyan("  [*] - значение будет изменено")}')
        log.info(f'{_colorize_green("  [+] - значение будет добавлено")}')
        log.info(f'  [.] - текущее значение и предлагаемое совпадают')
        log.info(f'config.yml:')
        _show_CommentedMap(template_config, dst_config)
        answ = input("Изменить config.yml? (y,n):") if confirm else 'y'
        if answ=='y' or answ=='Y':
            _update_CommentedMap(template_config, dst_config)
            yaml_tools.yaml_dump_to_file(dst_config, self.config_path)

    def create_project(self, project_config_path: str, package_path:str = "", need_import_src:bool = False, confirm: bool = True, rundds: bool = None) -> None:
        """ Создать новый прикладной проект (эксперементальная фича).
        Будет создана БД, в неё будет принят пакет разработки и стандратные шаблоны.

        Args:
            project_config_path: путь к файлу с описанием проекта
            package_path: путь к пакету разработки, который должен содержать бинарники
            need_import_src: признак необходимости принять исходники из указанного пакета разработки. По умолчанию - False
            confirm: признак необходимости выводить запрос на создание проекта. По умолчанию - True
            rundds: признак необходимости запускать DDS. По умолчанию - None, т.е. будет браться значение, определенное в config.yml
        """
        while (True):
            """Подгрузить необходимые модули.
            Выполняется именно тут, т.к:
            * если делать при загрузке - то модули-зависимости могут не успеть подгрузиться
            * DDS и DirectumRX может не быть не установлены и надо об этом сообщать
            """
            if 'sungero_deploy.tools.rxcmd' in sys.modules:
                from sungero_deploy.tools.rxcmd import RxCmd
            elif 'rx_plugin.rxcmd' in sys.modules:
                from rx_plugin.rxcmd import RxCmd
            else:
                log.error('Не найден модуль rxcmd')
                raise RuntimeError('Не найден модуль rxcmd')

            _show_config(project_config_path)
            answ = input("Создать новый проект? (y,n):") if confirm else 'y'
            if answ=='y' or answ=='Y':
                # остановить сервисы
                log.info(_colorize_green("Остановка сервисов"))
                all = All(self.config)
                all.down()

                # скорректировать etc\config.yml
                log.info(_colorize_green("Корректировка config.yml"))
                dst_config = _update_sungero_config(project_config_path, self.config_path)
                yaml_tools.yaml_dump_to_file(dst_config, self.config_path)
                time.sleep(2)

                # создать БД
                log.info(_colorize_green("Создать БД"))
                exitcode = SungeroDB(get_config_model(self.config_path)).up()
                if exitcode == -1:
                    log.error(f'Ошибка при создании БД')
                    return

                # поднять сервисы
                log.info(_colorize_green("Подъем сервисов"))
                all2 = All(get_config_model(self.config_path))
                all2.config_up()
                all2.up()
                all2.check()

                # принять пакет разработки в БД
                if package_path != "":
                    log.info(_colorize_green("Прием пакета разработки"))
                    DeploymentTool(self.config_path).deploy(package = package_path, init = True)

                    # импортировать шаблоны
                    log.info(_colorize_green("Перезапуск сервисов"))
                    all2.down()
                    all2.up()
                    all2.check()
                    log.info(_colorize_green("Импорт шаблонов"))
                    RxCmd(get_config_model(self.config_path)).import_templates()

                # обновить конфиги DevelopmentStudio и DeploymentToolUI
                # Подгрузка модулей выполняется именно тут, т.к:
                #   * если делать при загрузке - то модули-зависимости могут не успеть подгрузиться
                #   * DevelopmentStudio может не быть не установлены и надо об этом сообщать
                log.info(_colorize_green("Обновление конфига DevelopmentStudio"))
                if 'dds_plugin.development_studio' in sys.modules:
                    from dds_plugin.development_studio import DevelopmentStudio
                    DevelopmentStudio(self.config_path).generate_config_settings()
                    # принять пакет разработки с исходниками
                    if need_import_src:
                        log.info(_colorize_green("Прием пакета разработки"))
                        time.sleep(30) #подождать, когда сервисы загрузятся
                        DevelopmentStudio(self.config_path).run(f'--import-package {package_path}')
                else:
                    log.warning('Модуль development_studio plugin-а dds_plugin для компоненты DevelopmentStudio не найден.')
                log.info(_colorize_green("Обновление конфига DeploymentToolUI"))
                if 'dt_ui_plugin.deployment_tool_ui' in sys.modules:
                    from dt_ui_plugin.deployment_tool_ui import DeploymentToolUI
                    DeploymentToolUI(self.config_path).generate_config_settings()
                else:
                    log.warning('Модуль deployment_tool_ui plugin-а dt_ui_plugin для компоненты DeploymentToolUI не найден.')

                log.info("")
                log.info(_colorize_green("Новые параметры:"))
                self.current()

                # запустить DDS
                _run_dds(self.config_path, rundds, confirm)

                break
            elif answ=='n' or answ=='N':
                break

    def set(self, project_config_path: str, confirm: bool = True, rundds: bool = None) -> None:
        """ Переключиться на указанный прикладной проект

        Args:
            project_config_path: путь к файлу с описанием проекта
            confirm: признак необходимости выводить запрос на создание проекта. По умолчанию - True
            rundds: признак необходимости запускать DDS. По умолчанию - None, т.е. будет браться значение, определенное в config.yml
        """
        while (True):
            _show_config(project_config_path)
            answ = input("Переключиться на указанный проект? (y,n):") if confirm else 'y'
            if answ=='y' or answ=='Y':
                # остановить сервисы
                log.info(_colorize_green("Остановка сервисов"))
                all = All(self.config)
                all.down()

                # скорректировать etc\config.yml
                log.info(_colorize_green("Корректировка config.yml"))
                src_config = yaml_tools.load_yaml_from_file(project_config_path)
                dst_config = yaml_tools.load_yaml_from_file(self.config_path)
                dst_config["services_config"]["DevelopmentStudio"]['REPOSITORIES']["repository"]  = src_config["services_config"]["DevelopmentStudio"]['REPOSITORIES']["repository"].copy()
                dst_config["variables"]["purpose"] = src_config["variables"]["purpose"]
                dst_config["variables"]["database"] = src_config["variables"]["database"]
                dst_config["variables"]["home_path"] = src_config["variables"]["home_path"]
                dst_config["variables"]["home_path_src"]  = src_config["variables"]["home_path_src"]
                dst_config["variables"]["project_config_path"]  = project_config_path
                yaml_tools.yaml_dump_to_file(dst_config, self.config_path)
                time.sleep(2)

                # поднять сервисы
                log.info(_colorize_green("Подъем сервисов"))
                all2 = All(get_config_model(self.config_path))
                all2.config_up()
                all2.up()
                all2.check()

                # обновить конфиги DevelopmentStudio и DeploymentToolUI
                # Подгрузка модулей выполняется именно тут, т.к:
                #   * если делать при загрузке - то модули-зависимости могут не успеть подгрузиться
                #   * DevelopmentStudio может не быть не установлены и надо об этом сообщать
                log.info(_colorize_green("Обновление конфига DevelopmentStudio"))
                if 'dds_plugin.development_studio' in sys.modules:
                    from dds_plugin.development_studio import DevelopmentStudio
                    DevelopmentStudio(self.config_path).generate_config_settings()
                else:
                    log.warning('Модуль development_studio plugin-а dds_plugin для компоненты DevelopmentStudio не найден.')
                log.info(_colorize_green("Обновление конфига DeploymentToolUI"))
                if 'dt_ui_plugin.deployment_tool_ui' in sys.modules:
                    from dt_ui_plugin.deployment_tool_ui import DeploymentToolUI
                    DeploymentToolUI(self.config_path).generate_config_settings()
                else:
                    log.warning('Модуль deployment_tool_ui plugin-а dt_ui_plugin для компоненты DeploymentToolUI не найден.')

                log.info("")
                log.info(_colorize_green("Новые параметры:"))
                self.current()

                # запустить DDS
                _run_dds(self.config_path, rundds, confirm)

                break
            elif answ=='n' or answ=='N':
                break

    def generate_empty_project_config(self, new_config_path: str) -> None:
        """ Создать новый файл с описанием проекта

        Args:
            new_config_path: путь к файлу, который нужно создать
        """
        template_config="""# ключевые параметры проекта
variables:
    # Назначение проекта
    purpose: '<Назначение проекта>'
    # БД проекта
    database: '<База данных>'
    # Домашняя директория, относительно которой хранятся все данные сервисов.
    # Используется только в конфигурационном файле.
    home_path: '<Домашний каталог>'
    # Корневой каталог c репозиториями проекта
    home_path_src: '<корневой каталог репозитория проекта>'
# репозитории
services_config:
    DevelopmentStudio:
        REPOSITORIES:
            repository:
            -   '@folderName': '<папка репозитория-1>'
                '@solutionType': 'Work'
                '@url': '<url репозитория-1>'
            -   '@folderName': '<папка репозитория-2>'
                '@solutionType': 'Base'
                '@url': '<url репозитория-2>'
"""
        _generate_empty_config_by_template(new_config_path, template_config)

    def clone_project(self, src_project_config_path: str, dst_project_config_path: str, confirm: bool = True, rundds: bool = None) -> None:
        """ Сделать копию прикладного проекта (эксперементальная фича).
        Будет сделана копия БД и домашнего каталога проекта.

        Args:
            src_project_config_path: путь к файлу с описанием проекта-источника
            dst_project_config_path: путь к файлу с описанием проекта, в который надо скопировать
            confirm: признак необходимости выводить запрос на создание проекта. По умолчанию - True
            rundds: признак необходимости запускать DDS. По умолчанию - None, т.е. будет браться значение, определенное в config.yml
        """
        sungero_db = SungeroDB(get_config_model(self.config_path))

        src_project_config = yaml_tools.load_yaml_from_file(_get_check_file_path(src_project_config_path))
        src_sungero_config = _update_sungero_config(src_project_config_path, self.config_path)
        src_dbname = src_project_config["variables"]["database"]
        src_homepath = src_project_config["variables"]["home_path"]
        if not Path(src_homepath).is_dir():
            raise AssertionError(f'Исходный домашний каталог "{src_homepath}" не существует.')
        if not sungero_db.is_db_exist(src_dbname):
            raise AssertionError(f'Исходная база данных "{src_dbname}" не существует.')

        dst_project_config = yaml_tools.load_yaml_from_file(_get_check_file_path(dst_project_config_path))
        dst_dbname = dst_project_config["variables"]["database"]
        dst_homepath = dst_project_config["variables"]["home_path"]
        if Path(dst_homepath).is_dir():
            raise AssertionError(f'Целевой домашний каталог "{dst_homepath}" уже существует.')
        if sungero_db.is_db_exist(dst_dbname):
            raise AssertionError(f'Целевая база данных "{dst_dbname}" уже существует.')

        datadase_engine = src_sungero_config["common_config"]["DATABASE_ENGINE"]
        while (True):
            log.info('')
            log.info(Bold(f'Параметры клонирования проекта:'))
            log.info(f'database: {_colorize_green(src_dbname)} -> {_colorize_green(dst_dbname)}')
            log.info(f'homepath: {_colorize_green(src_homepath)} -> {_colorize_green(dst_homepath)}')

            answ = input("Клонировать проект? (y,n):") if confirm else 'y'
            if answ=='y' or answ=='Y':
                # Копирование БД
                log.info(_colorize_green(f'Копирование базы данных {src_dbname} в {dst_dbname}'))
                if datadase_engine == 'mssql':
                    _copy_database_mssql(self.config, src_dbname, dst_dbname)
                else:
                    _copy_database_postgresql(src_sungero_config, src_dbname, dst_dbname)
                # Сделать копию домашнего каталога проекта
                log.info(_colorize_green(f'Копирование домашнего каталога {src_homepath} {dst_homepath}'))
                shutil.copytree(src_homepath, dst_homepath)
                # переключить проект
                log.info("")
                self.set(dst_project_config_path, confirm, rundds)
                break
            elif answ=='n' or answ=='N':
                break

    def dds_wo_deploy(self, project_config_path: str) -> None:
        """ Запустить DDS для просмотра/редактирования исходников проекта без фактического переключения на него.
        При этом блокируется возможность публикации, чтобы не сломать текущий проект.

        Args:
            project_config_path: путь к файлу с описанием проекта, чьи исходники требуется открыть
         """
        if 'dds_plugin.development_studio' in sys.modules:
            # подготовить временные файлы для временных config.yml и _ConfigSettings.xml
            import tempfile
            dst_config_file_descriptor = tempfile.mkstemp(prefix="map_config_", suffix=".yml")
            config_settings_file_descriptor = tempfile.mkstemp(prefix="map_ConfigSettings_", suffix=".xml")
            os.close(dst_config_file_descriptor[0])
            os.close(config_settings_file_descriptor[0])
            dst_config_path = dst_config_file_descriptor[1]
            config_settings_file_name = config_settings_file_descriptor[1]
            log.info(f"Создан файл для временного config.yml: {dst_config_path}")
            log.info(f"Создан файл для временного _ConfigSettings.xml: {config_settings_file_name}")

            # подготовить специальный config.yml с проектом, чьи исходники надо открыть
            src_config = yaml_tools.load_yaml_from_file(project_config_path)
            dst_config = yaml_tools.load_yaml_from_file(self.config_path)
            dst_config["services_config"]["DevelopmentStudio"]['REPOSITORIES']["repository"]  = src_config["services_config"]["DevelopmentStudio"]['REPOSITORIES']["repository"].copy()
            dst_config["variables"]["purpose"] = src_config["variables"]["purpose"]
            dst_config["variables"]["database"] = src_config["variables"]["database"]
            dst_config["variables"]["home_path"] = src_config["variables"]["home_path"]
            dst_config["variables"]["home_path_src"]  = src_config["variables"]["home_path_src"]
            # отключить возможность публикации
            dst_config["services_config"]["DevelopmentStudio"]["LOCAL_WEB_RELATIVE_PATH"] = ""
            dst_config["services_config"]["DevelopmentStudio"]["LOCAL_SERVER_HTTP_PORT"] = ""
            dst_config["services_config"]["DevelopmentStudio"]["SERVICE_RUNNER_CONFIG_PATH"] = ""
            yaml_tools.yaml_dump_to_file(dst_config, dst_config_path)

            # подготовить специальный _ConfigSettings.xml для DDS
            from dds_plugin.development_studio import DevelopmentStudio
            from sungero_deploy.services_config import generate_service_config, get_default_tool_host_values_mapping
            dds = DevelopmentStudio(dst_config_path)
            generate_service_config(config_settings_file_name, get_config_model(dst_config_path), dds.instance_service,
                                get_default_tool_host_values_mapping())

            # запустить dds со специальным _ConfigSettings.xml
            cmd = f'"{dds._get_exe_path()}" --multi-instance --settings {config_settings_file_name}'
            exit_code = process.try_execute(cmd, encoding='cp1251')

            # удалить файлы с временными конфигами
            log.info("Удаление файлов временных конфигов.")
            os.remove(dst_config_path)
            os.remove(config_settings_file_name)

    #endregion

    #region manage distribution
    def build_distributions(self, distributions_config_path: str, destination_folder: str,
                            repo_folder: str, increment_version: bool = True) -> int:
        """ Построить дистрибутивы проекта

        Args:
            distributions_config_path: путь к yml-файл, в котором описаны дистрибутивы, которые нужно собрать
            destination_folder: папка, в которой будет создага папка с номером версии, внутри которой будут подготовлены дистрибутивы
            repo_folder: путь к локальному репозиторию, дистрибутивы которого надо собрать
            increment_version: признак необходимости увеличить номер версии решения после сборки дистрибутива
        """
        try:
            # Проверить переданные параметры
            if not Path(distributions_config_path).is_file():
                raise FileNotFoundError(f'Не найдет конфиг описания дистрибутивов проекта {distributions_config_path}')
            if not Path(destination_folder).is_dir():
                raise FileNotFoundError(f'Не найдет каталог назначения {destination_folder}')
            if not Path(PurePath(repo_folder)).is_dir():
                raise FileNotFoundError(f'Не найдет каталог назначения {repo_folder}')

            # загрузить конфиг с описанием дистрибутивов
            distr_config = yaml_tools.load_yaml_from_file(distributions_config_path)

            # достать номер номер версии и инициализиовать папку версии в папке назначения
            mtd_for_version = PurePath(repo_folder, distr_config["mtd_for_version"])
            if not Path(mtd_for_version).is_file():
                raise FileNotFoundError(f'Не найдет mtd-файл для получения версии решения {mtd_for_version}')
            mtd = yaml_tools.load_yaml_from_file(mtd_for_version)
            version = mtd["Version"]
            log.info(_colorize_green(f'Номер версии {version}'))
            version_folder = PurePath(destination_folder, version)
            io_tools._create_or_clean_dir(version_folder)

            # readme_string - массив строк для readme.md, в котором будет перечень дистрибутивов
            readme_strings = []
            readme_strings.append(distr_config["project"])
            readme_strings.append(f'Версия: {version}')
            readme_strings.append(f'Варианты дистрибутивов: ')
            for distr in distr_config["distributions"]:
                log.info(_colorize_green(f'Обработка дистрибутива {distr["id"]}'))
                readme_strings.append(f'* {distr["folder_name"]} - {distr["comment"]}')
                readme_strings.append("")

                # проинициализировать папку дистрибутива
                distr_folder =  PurePath(version_folder, distr["folder_name"])
                io_tools._create_or_clean_dir(distr_folder)
                # выгрузить пакеты разработки, при этом номер версии не увеличивать
                for devpack in distr["devpacks"]:
                    devpack_config = _get_full_path(repo_folder, devpack["config"])
                    if Path(devpack_config).is_file():
                        result_devpack = str(PurePath(distr_folder, devpack["result"]))
                        self.export_devpack(devpack_config, result_devpack, increment_version=False)
                    else:
                        log.warning(f'Не найден XML-конфиг {devpack_config}')
                # скопировать уникальные для дистрибутива файлы и каталоги
                if distr["files"] is not None:
                    for f in distr["files"]:
                        if f["src"] != "":
                            src = _get_full_path(repo_folder, f["src"])
                            dst = PurePath(distr_folder, f["dst"])
                            log.info(_colorize_green(f'  Копирование {src} -> {dst}'))
                            if Path(src).is_file():
                                shutil.copy(str(src), str(dst))
                            elif Path(src).is_dir():
                                shutil.copytree(str(src), str(dst))
                            else:
                                log.warning(f'Не найдет источник "{src}", указанный для дистрибутива {distr["id"]}')
                # скопировать каталоги и файлы, которые дублируются для каждого дистрибутива
                if distr_config["to_every_set"] is not None:
                    for f in distr_config["to_every_set"]:
                        if f["src"] != "":
                            src = _get_full_path(repo_folder, f["src"])
                            dst = PurePath(distr_folder, f["dst"])
                            log.info(_colorize_green(f'  Копирование {src} -> {dst}'))
                            if Path(src).is_file():
                                shutil.copy(str(src), str(dst))
                            elif Path(src).is_dir():
                                shutil.copytree(str(src), str(dst))
                            else:
                                log.warning(f'Не найдет источник "{src}", указанный для всех дистрибутивов')
                # создать архивы дистрибутивов
                if distr["zip_name"] != "":
                    zip_name = str(PurePath(version_folder, f'{distr["zip_name"]} v.{version}.zip'))
                    log.info(_colorize_green(f'Создать архив {zip_name}'))
                    io_tools.create_archive(zip_name, distr_folder)

            # сформировать readme.md для версии
            with open(str(PurePath(version_folder, 'readme.md')), "w", encoding='UTF-8') as f:
                f.write("\n".join(readme_strings))

            # увеличить номер версии, сформировав и удалив указанные пакеты разработки
            if increment_version:
                if distr_config["devpacks_for_increment_version"] is not None:
                    log.info(_colorize_green('Увеличить номер версии решения'))
                    for devpack in distr_config["devpacks_for_increment_version"]:
                        devpack_config = _get_full_path(repo_folder, devpack["config"])
                        if Path(devpack_config).is_file():
                            result_devpack = str(PurePath(version_folder, "__temp_devpack_for_inc_ver.dat"))
                            result_devpack_xml = str(PurePath(version_folder, "__temp_devpack_for_inc_ver.xml"))
                            self.export_devpack(devpack_config, result_devpack, increment_version=True)
                            os.remove(result_devpack)
                            os.remove(result_devpack_xml)
                        else:
                            log.warning(f'Не найден XML-конфиг {devpack_config}')
                else:
                    log.warning(f'Не найден параметр devpacks_for_increment_version - увеличение версии решения не будет выполнено')

            return 0
        except Exception as error:
            log.error(f'При формировании дистирибутивов возникла ошибка {error.value}')
            return 1

    def export_devpack(self, devpack_config_name: str, devpack_file_name: str, increment_version: bool = None, set_version: str = None) -> None:
        """Экспортировать пакет разработки

        Args:
            devpack_config_name: имя XML-файла с конфигурацией пакета разработки. Задает параметр --configuration
            devpack_file_name: путь к создаваемому файлу с пакетом разработки. Задает параметр --development-package
            increment_version: признак, который определяет нужно увеличивать номер версии модулей и решений или нет.
            set_version: номер версии, который надо установить. Задает параметр --set-version. . Если указано значение None - то не передается при вызове DDS
        """
        inc_ver_param = ""
        if increment_version is not None:
            inc_ver_param = f'--increment-version {increment_version}'
        set_ver_param = ""
        if set_version is not None:
            set_ver_param = f'--set-version {set_version}'

        """Подгрузить модуль DDS.
        Выполняется именно тут, т.к:
        * если делать при загрузке - то модули-зависимости могут не успеть подгрузиться
        * DDS может не быть не установлены и надо об этом сообщать
        """
        import sys
        if 'dds_plugin.development_studio' in sys.modules:
            from dds_plugin.development_studio import DevelopmentStudio
        else:
            log.error('Не найден модуль dds_plugin.development_studio')
            raise RuntimeError('Не найден модуль dds_plugin.development_studio')
        command = f' --configuration {devpack_config_name} --development-package {devpack_file_name} {inc_ver_param} {set_ver_param}'
        DevelopmentStudio(self.config_path).run(command=command)

    def generate_empty_distributions_config(self, new_config_path: str) -> None:
        """ Создать новый файл с описанием дистрибутивов проекта

        Args:
            new_config_path: путь к файлу, который нужно создать
        """
        template_config="""# Название проекта
project: ''

# mtd-файл, из которого берется номер текущей версии
mtd_for_version: '....Solution.Shared\Module.mtd'

# XML-конфиги, которые используются для формирования пакета разработки в процессе увеличения версии решения
devpacks_for_increment_version:
-   config: ''

# Файлы и каталоги, которые копируются в каждый дистрибутив
to_every_set:
-   'src': ''
    'dst': ''

# Описание дистрибутивов
distributions:
    # идентификатор дистритутива
-   'id': ''
    # описание сути дистрибутива
    'comment': ''
    # папка дистрибутива, создается внутри папки версии решения
    'folder_name': ''
    # Значимая часть имени zip-архива с дистрибутивом. Если указать пустую строку - архив не создается
    'zip_name': 'Образец '
    # Пакеты разработки, которые нужно поместить в дистрибутив
    'devpacks':
    -   'config': '.xml'
        'result': '.dat'
    # Уникальные файлы, которые нужно поместить в конкретный дистрибутив
    'files':
    -   'src': ''
        'dst': ''
"""
        _generate_empty_config_by_template(new_config_path, template_config)

    #endregion

    #region other
    def clear_log(self, root_logs: str = None, limit_day: int = 3) -> None:
        """Удалить старые логи. Чистит в root_logs и в подкаталогах.
        Предполагается, что последние символы имени файла лога - YYYY-MM-DD.log

        Args:
            root_logs: корневой каталог репозитория. Если не указан, то будут чиститься логи сервисов текущего instance
            limit_day: за сколько последних дней оставить логи. По умолчанию - 3. Если указать 0 - будут удалены все логи.
        """
        if root_logs is None:
            log_folders = []
            for s in self.config.services_config.values():
                if s.get('LOGS_PATH', None) is not None:
                    log_folders.append(s.get('LOGS_PATH', None))
            log_folders = set(log_folders)
        else:
            log_folders = set([root_logs])
        from datetime import datetime, timedelta
        limit_date = (datetime.now() - timedelta(days=limit_day)).strftime("%Y-%m-%d")
        for root_log in log_folders:
            for root, dirs, files in os.walk(root_log):
                for file in files:
                    date_subs = file[-14:-4]
                    if date_subs <= limit_date:
                        os.remove(os.path.join(root, file))

    def current(self) -> None:
        """ Показать параметры текущего проекта """
        log.info(f'Веб-клиент:          {_get_url(self.config)}')
        _show_config(self.config_path)

    def rx_version(self) -> None:
        """Показать версию RX"""
        ver = _get_rx_version()
        log.info(f'Directum RX: {ver}')

    def url(self) -> None:
        """Показать url для открытия веб-клиента текущего инстанса"""
        log.info(_get_url(self.config))

    def check_config(self, config_path: str) -> None:
        """ Показать содержимое указанного файла описания проекта

        Args:
            config_path: путь к файлу с описанием проекта
        """
        _show_config(config_path)

    @staticmethod
    def help() -> None:
        log.info('do map set - переключиться на проект, описаный в указанном yml-файла')
        log.info('do map generate_empty_project_config - создать заготовку для файла описания проекта')
        log.info('do map create_project - создать новый проект: новую БД, хранилище документов, принять пакет разработки, \
инициализировать его и принять стандартные шаблоны')
        log.info('do map update_config - изменить параметры в config.yml взяв значения из переданного файла')
        log.info('do map clone_project - клонировать проект (сделать копии БД и домашнего каталога)')
        log.info('do map dds_wo_deploy - запустить DevelopmentStudio для просмотра/редактирования исходников указанного проекта без возможности публикации')

        log.info('do map build_distributions - сформировать дистрибутивы решения')
        log.info('do map export_devpack - выгрузить пакет разработки')
        log.info('do map generate_empty_distributions_config - сформировать пустой конфиг с описанием дистрибутивов решения')
        log.info('do map clear_log - удалить старые логи')
        log.info('do map current - показать ключевую информацию из текущего config.yml')
        log.info('do map rx_version - показать версию Sungero')
        log.info('do map url - показать url для подключения к веб-клиенту текущего инстанса')
        log.info('do map check_config - показать ключевую информацию из указанного yml-файла описания проекта')

    #endregion
