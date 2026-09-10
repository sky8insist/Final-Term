from app.tools import morning_tools, session_tools


def test_dayend_tools_are_read_only_and_critic_has_no_tools():
    names = {tool.name for tool in [session_tools.get_current_session_state, session_tools.get_last_closure_status, morning_tools.get_last_night_plan, morning_tools.get_confirmed_items]}
    assert names == {"get_current_session_state", "get_last_closure_status", "get_last_night_plan", "get_confirmed_items"}
    assert all(not any(word in name for word in ("write", "delete", "persist")) for name in names)
