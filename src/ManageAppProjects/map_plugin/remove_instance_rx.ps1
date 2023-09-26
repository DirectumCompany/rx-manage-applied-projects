# установить указанный билд RX в указанную папку
# при открытии DirectumLauncher надо указать свободный порт и instance_name


Param ([string] $instance_root_dir_path,  #корневой каталог для установки инстансов
       [string] $instance_name
       )
Write-Host "Переданные параметры:"
Write-Host "  Корневой каталог:" $instance_root_dir_path
Write-Host "  Имя инстанса:" $instance_name
Write-Host ""

$instance_path = Join-Path $instance_root_dir_path  $instance_name

$is_exist_instance_path = Test-Path $instance_path -PathType Container 
if(!$is_exist_instance_path){
  Write-Host ""
  Write-Host "Не найден каталог '$instance_path' с инстансом $instance_name." -ForegroundColor Red
  Write-Host ""
  break
} else {
  Write-Host "Удаляем инстанс из каталога '$instance_path'." -ForegroundColor Green
}

$config_file_path = Join-Path $instance_path "etc\config.yml"
$is_exist_config_file_path = Test-Path $config_file_path -PathType Leaf
if(!$is_exist_config_file_path){
  Write-Host ""
  Write-Host "Не найден '$is_exist_config_file_path'." -ForegroundColor Red
  Write-Host ""
  break
}

$cfg_before_install = Get-Content $config_file_path -Encoding 'utf8' | Out-String | ConvertFrom-Yaml 
$instance_name = $cfg_before_install.variables.instance_name
Write-host $instance_name

Set-Location $instance_path
.\do.bat all down
Start-Sleep -Seconds 2

$sitename = "DirectumRX Web Site Name_$instance_name"
$sites = Get-IISSite
if ($sites.Name.IndexOf($sitename) -ne -1) {
  Remove-IISSite -Name $sitename
  Start-Sleep -Seconds 2
}

$poolname = "DirectumRX Web Site_$instance_name"
$poolname2 = "DirectumRX Web Site Name_$instance_name"
$pools = Get-IISAppPool
if ($pools.Name.IndexOf($poolname) -ne -1) {
  Remove-WebAppPool -Name $poolname
  Start-Sleep -Seconds 2
}
if ($pools.Name.IndexOf($poolname2) -ne -1) {
  Remove-WebAppPool -Name $poolname2
  Start-Sleep -Seconds 2
}

Set-Location $instance_root_dir_path

Remove-Item $instance_path -Recurse -Force

