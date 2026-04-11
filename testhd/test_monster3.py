"""测试 Monster3 活动"""
import gameplay

def test_monster3():
    """测试 monster3 活动的完整流程"""
    print("=" * 60)
    print("Monster3 活动测试")
    print("=" * 60)

    # 获取 monster3 活动
    monster3 = gameplay.g_HDInfo.get("Monster3")

    if not monster3:
        print("错误：未找到 Monster3 活动")
        return

    print(f"\n活动名称：{monster3.m_HDHame}")
    print(f"当前状态：{'开启' if monster3.m_bOpenHD else '关闭'}")

    # 模拟时间变化
    print("\n--- 模拟 5:00 ---")
    monster3.NewHour(5)
    print(f"活动状态：{'开启' if monster3.m_bOpenHD else '关闭'}")
    print(f"场景ID：{monster3.m_scene_id}")
    print(f"NPC数量：{len(monster3.m_npcs)}")

    print("\n--- 模拟 10:00 ---")
    monster3.NewHour(10)
    print(f"活动状态：{'开启' if monster3.m_bOpenHD else '关闭'}")
    print(f"场景ID：{monster3.m_scene_id}")
    print(f"NPC数量：{len(monster3.m_npcs)}")

    print("\n--- 再次测试开启 ---")
    monster3.NewHour(5)
    print(f"活动状态：{'开启' if monster3.m_bOpenHD else '关闭'}")

    print("\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)

if __name__ == "__main__":
    test_monster3()
