import gameplay

class CMonster(gameplay.CHuoDong):
    def __init__(self):
        super().__init__()
        self.m_bOpenHD = False

    def NewHour(self, iHour):
        if iHour == 10:
            self.OpenHD()
        elif iHour == 23:
            self.CloseHD()

    def OpenHD(self):
        self.m_bOpenHD = True

    def CloseHD(self):
        self.m_bOpenHD = False