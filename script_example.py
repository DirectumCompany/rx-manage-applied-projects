# отобразить доступные локальные переменные
log.info(pformat(locals()))

# проверить передан ли параметра arg1
if "arg1" not in locals():
    log.error("Пропущен обязательный параметр arg1")
    sys.exit(-1)

# вывести значение параметра arg1
log.info("Параметры запуска:")
log.info(f'  arg1={arg1}')

# отобразить путь к config.yml текущего экземпляра RX
log.info(f'Путь к config.yml: {self_map.config_path}')

# вызвать метод класса ManageAppliedProject
self_map.check_sdk(need_pause=False)

# вызвать функцию, определенную в map_installer.py
log.info(f'Версия RX: {_get_rx_version()}')