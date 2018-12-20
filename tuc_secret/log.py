import logging.handlers

rootLogger = logging.getLogger('')
rootLogger.setLevel(logging.INFO)

socketHandler = logging.handlers.SocketHandler('localhost', logging.handlers.DEFAULT_TCP_LOGGING_PORT)

rootLogger.addHandler(socketHandler)
