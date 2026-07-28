class KlineStream:

    def __init__(self, kline):
        self.kline = kline

    def handle_message(self, message):
        self.kline.update(message["data"][0])
