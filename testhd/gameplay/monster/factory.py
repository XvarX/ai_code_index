"""怪物工厂"""
class MonsterFactory:
    def create(self, monster_type):
        """工厂方法创建怪物"""
        manager = MonsterManager()
        return manager.create_monster(monster_type)
