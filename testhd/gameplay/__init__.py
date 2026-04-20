class CHuoDong():
    def __init__(self):
        self.m_HDHame = ""

    def Init(self, hdhame):
        self.m_HDHame = hdhame

    def NewHour(self, iHour):
        pass


g_HDInfo = {}
from . import monster
from . import monster2
from . import monster3
from . import monster4
from . import monster5
from . import box
g_HDInfo["Monster"] = monster.CMonster()
g_HDInfo["Monster"].Init("Monster")
g_HDInfo["Monster2"] = monster2.CMonster2()
g_HDInfo["Monster2"].Init("Monster2")
g_HDInfo["Monster3"] = monster3.CMonster3()
g_HDInfo["Monster3"].Init("Monster3")
g_HDInfo["Monster4"] = monster4.CMonster4()
g_HDInfo["Monster4"].Init("Monster4")
g_HDInfo["Monster5"] = monster5.CMonster5()
g_HDInfo["Monster5"].Init("Monster5")
g_HDInfo["Box"] = box.CBox()
g_HDInfo["Box"].Init("Box")

