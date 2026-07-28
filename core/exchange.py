from abc import ABC, abstractmethod


class Exchange(ABC):

    @abstractmethod
    def connect(self):
        pass

    @abstractmethod
    def subscribe_trade(self, symbol, callback):
        pass

    @abstractmethod
    def subscribe_orderbook(self, symbol, callback):
        pass
