# установить указанный билд RX в указанную папку
# при открытии DirectumLauncher надо указать свободный порт и instance_name
Param ([string] $rx_instaler_dir_path,    #каталог с дистрибутивом устанавливаемого билда
       [string] $instance_root_dir_path,  #корневой каталог для установки инстансов
       [string] $instance_name,           #имя инстанса
       [int] $port,                       #port
       [string] $map_plugin_path,         #каталог с плагином MAP
       [string] $cfg_before_install_path, #конфиг для обновления config.yml перед установкой
       [string] $cfg_after_install_path   #конфиг для обновления config.yml после установки
       )
Write-Host "Переданные параметры:"
Write-Host "  Каталог с дистрибутивом:" $rx_instaler_dir_path
Write-Host "  Корневой каталог:" $instance_root_dir_path
Write-Host "  Имя инстанса:" $instance_name
Write-Host "  Порт:" $port
Write-Host "  Каталог с плагином MAP:" $map_plugin_path
Write-Host "  Конфиг для применения до установки:" $cfg_before_install_path
Write-Host "  Конфиг для применения после установки:" $cfg_after_install_path
Write-Host ""

$dst_path = Join-Path $instance_root_dir_path  $instance_name

$is_error = $false

#проверить корректность переданных параметров
$is_exist_rx_instaler_dir_path = Test-Path $rx_instaler_dir_path -PathType Container 
if(!$is_exist_rx_instaler_dir_path){
  Write-Host ""
  Write-Host "Не найден каталог '$rx_instaler_dir_path' с дистрибутивом RX." -ForegroundColor Red
  Write-Host ""
  $is_error = $true
} else {
  Write-Host "Найден каталог '$rx_instaler_dir_path' с дистрибутивом RX." -ForegroundColor Green
}

$is_exist_rx_instaler_dir_path = Test-Path $dst_path -PathType Container 
if($is_exist_rx_instaler_dir_path){
  Write-Host ""
  Write-Host "Каталог '$dst_path' назначения уже существует." -ForegroundColor Red
  Write-Host ""
  $is_error = $true
} else {
  Write-Host "Будет создан каталог '$dst_path'" -ForegroundColor Green
}

$out = (netstat -an | findstr /i :$port)  | Out-String

if ($out -ne "") {
  Write-Host "Порт $port занят" -ForegroundColor Red
  Write-Host $out
  $is_error = $true
} else {
  Write-Host "Порт свободен: " $port -ForegroundColor Green
}

$is_exist_map_plugin_path = Test-Path $map_plugin_path -PathType Container 
if(!$is_exist_map_plugin_path){
  Write-Host ""
  Write-Host "Не найден каталог '$map_plugin_path' с плагином Manage Applied Tools." -ForegroundColor Red
  Write-Host ""
  $is_error = $true
}

$is_exist_cfg_before_install_path = Test-Path $cfg_before_install_path -PathType Leaf
if(!$is_exist_cfg_before_install_path){
  Write-Host ""
  Write-Host "Не найден конфиг '$cfg_before_install_path' с параметрыми до-установки." -ForegroundColor Red
  Write-Host ""
  $is_error = $true
}

$is_exist_cfg_after_install_path = Test-Path $cfg_after_install_path -PathType Leaf
if(!$is_exist_cfg_after_install_path){
  Write-Host ""
  Write-Host "Не найден конфиг '$cfg_after_install_path' с параметрыми после-установки." -ForegroundColor Red
  Write-Host ""
  $is_error = $true
}

#проверить существование пула приложений
$poolname = "DirectumRX Web Site_$instance_name"
$pools = Get-IISAppPool
if ($pools.Name.IndexOf($poolname) -ne -1) {
  Write-Host "Пул приложений '$poolname' для инстанса уже существует."  -ForegroundColor Red
  $is_error = $true
} else {
  Write-Host "Пул приложений '$poolname' будет создан."  -ForegroundColor Green
}

if ($is_error) {
  break
}

Write-Host "Установка"

#Создать каталог и перейти в него
mkdir $dst_path
#cd /D $dst_path
Set-Location $dst_path

# Распаковать DL
tar -xf $rx_instaler_dir_path\DirectumLauncher.zip  -C $dst_path

#Вычислить устанавливаемую версию RX
$version_file_path = Join-Path $rx_instaler_dir_path "version.json"
$is_exists_version_file = Test-Path $version_file_path -PathType Leaf
if ($is_exists_version_file) {
  $version_file = Get-Content $version_file_path | Out-String | ConvertFrom-Json
  $version = $version_file.DirectumRX.Split('.')[0]+"."+$version_file.DirectumRX.Split('.')[1]
}
else {
  $manifest = Get-Content $dst_path\manifest.json | Out-String | ConvertFrom-Json
  $version = $manifest.version.Split('.')[0]+"."+$manifest.version.Split('.')[1]
}
Write-Host "Устанавливаем RX $version"

#создать config.yml и сразу задать имя инстанса и порт
$cfg = Get-Content -Path $dst_path\etc\config.yml.example -Encoding 'utf8' 
foreach ($line in $cfg){
  if ($line.StartsWith("    http_port:")){
    Add-Content -Path $dst_path\etc\config.yml -Value "    http_port: $port" -Encoding 'utf8' 
  } else {
    Add-Content -Path $dst_path\etc\config.yml -Value $line -Encoding 'utf8' 
  }
  if ($line.Contains("variables:")){
    Add-Content -Path $dst_path\etc\config.yml -Value "    instance_name: '$instance_name'" -Encoding 'utf8' 
    Add-Content -Path $dst_path\etc\config.yml -Value "    instance_root_path: '$instance_root_dir_path'" -Encoding 'utf8' 
  }
}

# Установить компоненты RX
if ($version -eq "4.2") {
  Write-Host 4.2
  .\do.bat components add_package $rx_instaler_dir_path\DevelopmentStudio.zip 
  .\do.bat components add_package $rx_instaler_dir_path\DeploymentTool.zip 
} elseif ($version -in @("4.3", "4.4")) {
  Write-Host 4.3, 4.4
  .\do.bat components add_package $rx_instaler_dir_path\DevelopmentStudio.zip 
  .\do.bat components add_package $rx_instaler_dir_path\DirectumRX.zip 
  .\do.bat components add_package $rx_instaler_dir_path\DeploymentTool.zip 
} elseif ($version -in @("4.5", "4.6", "4.7", "4.8")) {
  Write-Host @("4.5", "4.6", "4.7", "4.8")
  .\do.bat components add_package $rx_instaler_dir_path\Platform.zip
  .\do.bat components add_package $rx_instaler_dir_path\DevelopmentStudio.zip 
  .\do.bat components add_package $rx_instaler_dir_path\DirectumRX.zip 
  .\do.bat components add_package $rx_instaler_dir_path\DeploymentTool.zip 
} else {
  Write-Host "Версия $version не поддерживается" -ForegroundColor Red
  break
}

.\do.bat dds install
.\do.bat install_plugin $map_plugin_path


# Проверить версии SDK
Do 
{
  $check_result = (.\do.bat map check_sdk)  | Out-String
  $match_result = $check_result | Select-String -Pattern ' Ok' -AllMatches
  if ($match_result.Matches.Length -ne 4) {
    .\do.bat map check_sdk
    Write-Host "Установите необходимые компоненты"
    pause  
  }
  else {
    break
  }
} While ($true)

#подготовить config.yml к установке
.\do.bat map update_config $cfg_before_install_path --confirm=False  --need_pause=False

# Удалить базу данных, если она есть
$cfg_before_install = Get-Content $cfg_before_install_path -Encoding 'utf8' | Out-String | ConvertFrom-Yaml 
$dbengine = $cfg_before_install.common_config.DATABASE_ENGINE
$connection_string = $cfg_before_install.common_config.CONNECTION_STRING

$exe_file = ""
$arg_list = ""
if ($dbengine.ToLower() -eq "mssql") {
  #CONNECTION_STRING: 'data source=localhost;initial catalog=rx_install;user id=sa2;Password=1111'

  $exe_file = "sqlcmd.exe"
  foreach($param in $connection_string.Split(";")) {
     $key = $param.TrimStart().Split("=")[0].ToLower()
     $value = $param.TrimStart().Split("=")[1]
     if ($key.StartsWith("data source"))  {
       $arg_list = $arg_list +" -S $value"
     }
     if ($key.StartsWith("user id"))  {
       $arg_list = $arg_list + " -U $value"
     }
     if ($key.StartsWith("password"))  {
       $arg_list = $arg_list + " -P $value"
     }
     if ($key.StartsWith("initial catalog"))  {
       $dbname = $value
     }
  }
  $arg_list = $arg_list + ' -Q "if exists(select * from sysdatabases where name ='''+$dbname+''') drop database '+$dbname+'"'
}

if ($dbengine.ToLower() -eq "postgres") {
  #CONNECTION_STRING: 'server=localhost;port=5432;database=rx_install;user id=dbadmin;Password=1111'

  $postgresql_bin = $cfg_before_install.manage_applied_projects.postgresql_bin
  $exe_file = '"'+$postgresql_bin+'\dropdb.exe"'
  $arg_list =  ' --if-exists --force'
  foreach($param in $connection_string.Split(";")) {
     $key = $param.TrimStart().Split("=")[0].ToLower()
     $value = $param.TrimStart().Split("=")[1]
     if ($key.StartsWith("server"))  {
       $arg_list = $arg_list +" --host=$value"
     }
     if ($key.StartsWith("port"))  {
       $arg_list = $arg_list + " --port=$value"
     }
     if ($key.StartsWith("user id"))  {
       $arg_list = $arg_list + " --username=$value"
     }
     if ($key.StartsWith("database"))  {
       $dbname = $value
     }
  }
  $arg_list = $arg_list + ' --no-password '+$dbname
}
Start-Process -FilePath $exe_file -ArgumentList $arg_list


#=============== запустить установку
Start-Process -FilePath .\DirectumLauncher.exe -ArgumentList "--host=0.0.0.0" -Wait

#=============== скорректировать конфиг
.\do.bat map update_config $cfg_after_install_path  --confirm=False  --need_pause=False
