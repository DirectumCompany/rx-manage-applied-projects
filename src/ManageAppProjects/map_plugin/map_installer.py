# coding: utf-8
""" Модуль плагина для управления прикладными проектами  """
from asyncore import write
import pathlib
from pprint import pprint
from typing import Optional, Dict, Any
import termcolor
import time
import pprint
import shutil
from pathlib import PurePath, Path
import os

from fire.formatting import Bold

from sungero_deploy.all import All
from sungero_deploy.static_controller import StaticController
from components.base_component import BaseComponent
from components.component_manager import component
from py_common.logger import log
from sungero_deploy.deployment_tool import DeploymentTool
from common_plugin import yaml_tools
from sungero_deploy.scripts_config import get_config_model
from sungero_deploy.tools.sungerodb import SungeroDB
from py_common import io_tools
from sungero_tenants.dbtools import create_database_from_backup, create_database_backup, is_database_exists
from sungero_tenants.tenant_model import TenantModel

MANAGE_APPLIED_PROJECTS_ALIAS = 'map'

def _colorize(x):
    return termcolor.colored(x, color="green", attrs=["bold"])

def _show_config(config_path):
    config = yaml_tools.load_yaml_from_file(_get_check_file_path(config_path))
    vars = config.get("variables")
    repos = config.get("services_config").get("DevelopmentStudio").get('REPOSITORIES').get("repository")
    maxlen = 0
    for repo in repos:
        if maxlen < len(repo.get("@folderName")):
            maxlen = len(repo.get("@folderName"))
    log.info(Bold(f'Назначение:    {vars.get("purpose")}'))
    log.info(f'database:      {_colorize(vars.get("database"))}')
    log.info(f'home_path:     {_colorize(vars.get("home_path"))}')
    log.info(f'home_path_src: {_colorize(vars.get("home_path_src"))}')
    log.info('repositories:')
    for repo in repos:
        log.info(f'  folder: {_colorize(repo.get("@folderName").ljust(maxlen)):} solutiontype: {_colorize(repo.get("@solutionType"))}  url: {_colorize(repo.get("@url"))}')

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
        log.info(_colorize(f'Создан файл {new_config_path}.'))
    else:
        log.error(f'Файл {new_config_path} уже существует.')

def _update_sungero_config(project_config_path, sungero_config_path):
    """Преобразовать текущий config.yml в соотвтетствии с указанным конфигом проекта.
    Преобразование выполняется без сохранения на диске
    
    Args:
        * project_config_path - путь к конфигу проекта
    
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
    return dst_config

@component(alias=MANAGE_APPLIED_PROJECTS_ALIAS)
class ManageAppliedProject(BaseComponent):
    """ Компонент Изменение проекта. """

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

    def current(self) -> None:
        """ Показать параметры текущего проекта """
        _show_config(self.config_path)

    def check_config(self, config_path: str) -> None:
        """ Показать содержимое указанного файла описания проекта

        Args:
            config_path: путь к файлу с описанием проекта
        """
        _show_config(config_path)

    @staticmethod
    def help() -> None:
        log.info('do map current - показать ключевую информацию из текущего config.yml')
        log.info('do map check_config - показать ключевую информацию из указанного yml-файла описания проекта')
        log.info('do map set - переключиться на проект, описаный в указанном yml-файла')
        log.info('do map generate_empty_project_config - создать заготовку для файла описания проекта')
        log.info('do map create_project - создать новый проект: новую БД, хранилище документов, принять пакет разработки, \
инициализировать его и принять стандартные шаблоны')
        log.info('do map clone_project - клонировать проект (сделать копии БД и домашнего каталога)')
        log.info('do map export_devpack - выгрузить пакет разработки')
        log.info('do map build_distributions - сформировать дистрибутивы решения')
        log.info('do map generate_empty_distributions_config - сформировать пустой конфиг с описанием дистрибутивов решения')
        log.info('do map clear_log - удалить старые логи')

    def create_project(self, project_config_path: str, package_path:str, need_import_src:bool = False, confirm: bool = True) -> None:
        """ Создать новый прикладной проект (эксперементальная фича).
        Будет создана БД, в неё будет принят пакет разработки и стандратные шаблоны.

        Args:
            project_config_path: путь к файлу с описанием проекта
            package_path: путь к пакету разработки, который должен содержать бинарники
            need_import_src: признак необходимости принять исходники из указанного пакета разработки. По умолчанию - False
            confirm: признак необходимости выводить запрос на создание проекта. По умолчанию - True
        """
        while (True):
            """Подгрузить необходимые модули.
            Выполняется именно тут, т.к:
            * если делать при загрузке - то модули-зависимости могут не успеть подгрузиться
            * DDS и DirectumRX может не быть не установлены и надо об этом сообщать
            """
            import sys
            if 'dds_plugin.development_studio' in sys.modules:
                from dds_plugin.development_studio import DevelopmentStudio
            else:
                log.error('Не найден модуль dds_plugin.development_studio')
                raise RuntimeError('Не найден модуль dds_plugin.development_studio')

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
                log.info(_colorize("Остановка сервисов"))
                all = All(self.config)
                all.down()

                # скорректировать etc\config.yml
                log.info(_colorize("Корректировка config.yml"))
                dst_config = _update_sungero_config(project_config_path, self.config_path)
                yaml_tools.yaml_dump_to_file(dst_config, self.config_path)
                time.sleep(2)

                # создать БД
                log.info(_colorize("Создать БД"))
                exitcode = SungeroDB(get_config_model(self.config_path)).up()
                if exitcode == -1:
                    log.error(f'Ошибка при создании БД')
                    return

                # поднять сервисы
                log.info(_colorize("Подъем сервисов"))
                all2 = All(get_config_model(self.config_path))
                all2.config_up()
                all2.up()

                # обновить конфиг DDS
                log.info(_colorize("Обновление конфига DDS"))
                DevelopmentStudio(self.config_path).generate_config_settings()

                # принять пакет разработки в БД
                log.info(_colorize("Ожидание загрузки сервисов"))
                time.sleep(30) #подождать, когда сервисы загрузятся - без этого возникает ошибка
                log.info(_colorize("Прием пакета разработки"))
                DeploymentTool(self.config_path).deploy(package = package_path, init = True)

                # импортировать шаблоны
                log.info(_colorize("Ожидание загрузки сервисов"))
                time.sleep(30) #подождать, когда сервисы загрузятся - без этого возникает ошибка
                log.info(_colorize("Импорт шаблонов"))
                RxCmd(get_config_model(self.config_path)).import_templates()

                # принять пакет разработки с исходниками
                if need_import_src:
                    log.info(_colorize("Прием пакета разработки"))
                    time.sleep(30) #подождать, когда сервисы загрузятся
                    DevelopmentStudio(self.config_path).run(f'--import-package {package_path}')

                log.info("")
                log.info(_colorize("Новые параметры:"))
                self.current()
                break
            elif answ=='n' or answ=='N':
                break

    def set(self, project_config_path: str, confirm: bool = True) -> None:
        """ Переключиться на указанный прикладной проект

        Args:
            project_config_path: путь к файлу с описанием проекта
            confirm: признак необходимости выводить запрос на создание проекта. По умолчанию - True
        """
        while (True):
            _show_config(project_config_path)
            answ = input("Переключиться на указанный проект? (y,n):") if confirm else 'y'
            if answ=='y' or answ=='Y':
                # остановить сервисы
                log.info(_colorize("Остановка сервисов"))
                all = All(self.config)
                all.down()

                # скорректировать etc\config.yml
                log.info(_colorize("Корректировка config.yml"))
                src_config = yaml_tools.load_yaml_from_file(project_config_path)
                dst_config = yaml_tools.load_yaml_from_file(self.config_path)
                dst_config["services_config"]["DevelopmentStudio"]['REPOSITORIES']["repository"]  = src_config["services_config"]["DevelopmentStudio"]['REPOSITORIES']["repository"].copy()
                dst_config["variables"]["purpose"] = src_config["variables"]["purpose"]
                dst_config["variables"]["database"] = src_config["variables"]["database"]
                dst_config["variables"]["home_path"] = src_config["variables"]["home_path"]
                dst_config["variables"]["home_path_src"]  = src_config["variables"]["home_path_src"]
                yaml_tools.yaml_dump_to_file(dst_config, self.config_path)
                time.sleep(2)

                # поднять сервисы
                log.info(_colorize("Подъем сервисов"))
                all2 = All(get_config_model(self.config_path))
                all2.config_up()
                all2.up()

                # обновить конфиг DDS
                log.info(_colorize("Обновление конфига DDS"))
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
                DevelopmentStudio(self.config_path).generate_config_settings()

                log.info("")
                log.info(_colorize("Новые параметры:"))
                self.current()
                break
            elif answ=='n' or answ=='N':
                break

    def build_distributions(self, distriputions_config_path: str, destination_folder: str,
                            repo_folder: str, increment_version: bool = True) -> int:
        """Построить дистрибутивы проекта

        Args:
        * distriputions_config_path - путь к yml-файл, в котором описаны дистрибутивы, которые нужно собрать
        * destination_folder - папка, в которой будет создага папка с номером версии, внутри которой будут подготовлены дистрибутивы
        * repo_folder - путь к локальному репозиторию, дистрибутивы которого надо собрать
        """
        try:
            # Проверить переданные параметры
            if not Path(distriputions_config_path).is_file():
                raise FileNotFoundError(f'Не найдет конфиг описания дистрибутивов проекта {distriputions_config_path}')
            if not Path(destination_folder).is_dir():
                raise FileNotFoundError(f'Не найдет каталог назначения {destination_folder}')
            if not Path(PurePath(repo_folder)).is_dir():
                raise FileNotFoundError(f'Не найдет каталог назначения {repo_folder}')

            # загрузить конфиг с описанием дистрибутивов
            distr_config = yaml_tools.load_yaml_from_file(distriputions_config_path)

            # достать номер номер версии и инициализиовать папку версии в папке назначения
            mtd_for_version = PurePath(repo_folder, distr_config["mtd_for_version"])
            if not Path(mtd_for_version).is_file():
                raise FileNotFoundError(f'Не найдет mtd-файл для получения версии решения {mtd_for_version}')
            mtd = yaml_tools.load_yaml_from_file(mtd_for_version)
            version = mtd["Version"]
            log.info(_colorize(f'Номер версии {version}'))
            version_folder = PurePath(destination_folder, version)
            io_tools._create_or_clean_dir(version_folder)

            # readme_string - массив строк для readme.md, в котором будет перечень дистрибутивов
            readme_strings = []
            readme_strings.append(distr_config["project"])
            readme_strings.append(f'Версия: {version}')
            readme_strings.append(f'Варианты дистрибутивов: ')
            for distr in distr_config["distributions"]:
                log.info(_colorize(f'Обработка дистрибутива {distr["id"]}'))
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
                            log.info(_colorize(f'  Копирование {src} -> {dst}'))
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
                            log.info(_colorize(f'  Копирование {src} -> {dst}'))
                            if Path(src).is_file():
                                shutil.copy(str(src), str(dst))
                            elif Path(src).is_dir():
                                shutil.copytree(str(src), str(dst))
                            else:
                                log.warning(f'Не найдет источник "{src}", указанный для всех дистрибутивов')
                # создать архивы дистрибутивов
                if distr["zip_name"] != "":
                    zip_name = str(PurePath(version_folder, f'{distr["zip_name"]} v.{version}.zip'))
                    log.info(_colorize(f'Создать архив {zip_name}'))
                    io_tools.create_archive(zip_name, distr_folder)

            # сформировать readme.md для версии
            with open(str(PurePath(version_folder, 'readme.md')), "w", encoding='UTF-8') as f:
                f.write("\n".join(readme_strings))

            # увеличить номер версии, сформировав и удалив указанные пакеты разработки
            if increment_version:
                if distr_config["devpacks_for_increment_version"] is not None:
                    log.info(_colorize('Увеличить номер версии решения'))
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
            * devpack_config_name - имя XML-файла с конфигурацией пакета разработки. Задает параметр --configuration
            * devpack_file_name - путь к создаваемому файлу с пакетом разработки. Задает параметр --development-package
            * increment_version - признак, который определяет нужно увеличивать номер версии модулей и решений или нет.
            Задает параметр --increment-version. Если указано значение None - то не передается при вызове DDS
            * set_version - номер версии, который надо устаноить. Задает параметр --set-version. . Если указано значение None - то не передается при вызове DDS
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

    def generate_empty_project_config(self, new_config_path: str) -> None:
        """ Создать новый файл с описанием проекта

        Args:
            new_config_path - путь к файлу, который нужно создать
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

    def generate_empty_distributions_config(self, new_config_path: str) -> None:
        """ Создать новый файл с описанием дистрибутивов проекта

        Args:
            new_config_path - путь к файлу, который нужно создать
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

    def clear_log(self, root_logs: str = None, limit_day: int = 3) -> None:
        """Удалить старые логи. Чистит в root_logs и в подкаталогах.
        Предполагается, что последние символы имени файла лога - YYYY-MM-DD.log

        Args:
            * root_logs - корневой каталог репозитория. Если не указан, то будут чиститься логи сервисов текущего instance
            * limit_day - за сколько последних дней оставить логи. По умолчанию - 3.
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


    def clone_project(self, src_project_config_path: str, dst_project_config_path: str, confirm: bool = True) -> None:
        """ Сделать копию прикладного проекта (эксперементальная фича).
        Будет сделана копия БД и домашнего каталога проекта.

        Args:
            src_project_config_path: путь к файлу с описанием проекта-источника
            dst_project_config_path: путь к файлу с описанием проекта, в который надо скопировать
            confirm: признак необходимости выводить запрос на создание проекта. По умолчанию - True
        """

        src_project_config = yaml_tools.load_yaml_from_file(src_project_config_path)
        src_sungero_config = _update_sungero_config(src_project_config_path, self.config_path)
        src_dbname = src_project_config["variables"]["database"]
        src_homepath = src_project_config["variables"]["home_path"]

        if src_sungero_config["common_config"]["DATABASE_ENGINE"] == 'postgres':
            raise AssertionError(f'В этой команде PostgreSQL не поддерживается.')
        if not Path(src_homepath).is_dir():
            raise AssertionError(f'Исходный домашний каталог "{src_homepath}" не существует.')
        if not is_database_exists(self.config, src_dbname):
            raise AssertionError(f'Исходная база данных "{src_dbname}" не существует.')

        dst_project_config = yaml_tools.load_yaml_from_file(dst_project_config_path)
        dst_sungero_config = _update_sungero_config(dst_project_config_path, self.config_path)
        dst_dbname = dst_project_config["variables"]["database"]
        dst_homepath = dst_project_config["variables"]["home_path"]
        if Path(dst_homepath).is_dir():
            raise AssertionError(f'Целевой домашний каталог "{dst_homepath}" уже существует.')
        if is_database_exists(self.config, dst_dbname):
            raise AssertionError(f'Целевая база данных "{dst_dbname}" уже существует.')

        while (True):

            print(f'БД-источник: {src_project_config["variables"]["database"]}')
            print(f'БД-приемник: {dst_project_config["variables"]["database"]}')

            log.info(Bold(f'Параметры клонирования проекта:'))
            log.info(f'database: {_colorize(src_dbname)} -> {_colorize(dst_dbname)}')
            log.info(f'homepath: {_colorize(src_homepath)} -> {_colorize(dst_homepath)}')

            answ = input("Клонировать проект? (y,n):") if confirm else 'y'
            if answ=='y' or answ=='Y':
                # Сделать копию БД
                log.info(_colorize(f'Создание резеврной копии базы данных {src_dbname}'))
                create_database_backup(self.config, src_dbname)
                # Восстановить БД
                # костыль - создаем модель псевдотенант, т.к. create_database_from_backup требует тип TenantModel
                log.info(_colorize(f'Восстановление БД {dst_dbname}'))
                tenant_model = TenantModel({'db': dst_dbname})
                create_database_from_backup(self.config, src_dbname, tenant_model)
                # Сделать копию домашнего каталога проекта
                log.info(_colorize(f'Копирование домашнего каталога {src_homepath} {dst_homepath}'))
                shutil.copytree(src_homepath, dst_homepath)
                # переключить проект
                self.set(dst_project_config_path)
                break
            elif answ=='n' or answ=='N':
                break
