# отобразить доступные локальные переменные
log.info(pformat(locals()))

# arg1 - обязательный параметр
if "arg1" not in locals():
    log.error("Пропущен обязательный параметр arg1")
    sys.exit(-1)

# arg2 - необязательный параметр
if "arg2" not in locals():
    arg2 = None

# вывести значение параметров скрипта
log.info("Параметры запуска:")
log.info(f'  arg1={arg1}')
log.info(f'  arg2={arg2}')

# пример использования переменных и методов класса ManageAppliedProject
log.info(f'Путь к config.yml: {self_map.config_path}') # отобразить путь к config.yml текущего экземпляра RX
self_map.check_sdk(need_pause=False) # вызвать метод класса ManageAppliedProject
# пример использования функций, определенных в map_installer.py
log.info(f'Версия RX: {_get_rx_version()}')

# пример использования функций и классов, определяемых в скрипте
def main_func(arg1, arg2, self_map):
    """ главная функция, внутри которой определяются локальные функции и классы
        в функцию передаются все переменные из основного тела скрипта
    """
    log.info(f'Версия RX: {_get_rx_version()}')

    log.info(f'main_func() run')
    log.info(f'  arg1={arg1}')
    log.info(f'  arg2={arg2}')

    class Foo():
       def __init__(self, name):
           self.name = name

    def f1():
        log.info(f'  f1() run')
        log.info(f'    arg1={arg1}')
    def f2():
        log.info(f'  f2() run')
        log.info(f'    arg2={arg2}')
        f1()
    f1()
    f2()
    f = Foo("f")
    log.info(f'  class f={f.name}')

# запуск главной функции
main_func(arg1, arg2, self_map)