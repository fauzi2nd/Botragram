from abc import ABC, abstractmethod


class Strategy(ABC):

    @abstractmethod
    def analyze(self, market):
        pass
