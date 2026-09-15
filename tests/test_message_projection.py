import json

from imhungry.conversations import project_messages


def use(name, key):
    return {'role': 'assistant', 'content': [{'toolUse': {'name': name, 'toolUseId': key, 'input': {'secret': 'PRIVATE'}}}]}


def result(key, data, status='success'):
    return {'role': 'user', 'content': [{'toolResult': {'toolUseId': key, 'status': status, 'content': [{'text': json.dumps(data)}]}}]}


def test_tool_outcomes_are_sanitized_and_attached_to_reply():
    history = [{'role': 'user', 'content': [{'text': 'Help with dinner'}]},
               use('lookup_restaurant_menu', 'a'), result('a', {'status': 'unavailable', 'fallback': {'reason': 'PRIVATE'}}),
               use('estimate_food_nutrition', 'b'), result('b', {'error': {'message': 'PRIVATE'}}),
               use('estimate_food_nutrition', 'c'), result('c', {'nutrition': {'energy_kcal': 500}}),
               use('PRIVATE_unknown_tool', 'd'), result('d', {'private': 'PRIVATE'}),
               {'role': 'assistant', 'content': [{'text': 'Here is my answer'}]}]
    public = project_messages(history)
    assert len(public) == 2
    assert public[1]['tool_activity'] == [
        {'name': 'lookup_restaurant_menu', 'status': 'unavailable'},
        {'name': 'estimate_food_nutrition', 'status': 'failed'},
        {'name': 'estimate_food_nutrition', 'status': 'completed'},
    ]
    assert 'PRIVATE' not in json.dumps(public)
    assert 'toolUseId' not in json.dumps(public)
    assert 'energy_kcal' not in json.dumps(public)


def test_sdk_failure_and_missing_result_do_not_claim_completion():
    public = project_messages([use('log_food', 'a'), result('a', {}, 'error'), use('get_user_profile', 'b')])
    assert public == [{'role': 'assistant', 'text': '', 'tool_activity': [
        {'name': 'log_food', 'status': 'failed'}, {'name': 'get_user_profile', 'status': 'unconfirmed'}]}]


def test_text_only_history_is_unchanged():
    assert project_messages([{'role': 'user', 'content': [{'text': 'Hi'}]}, {'role': 'assistant', 'content': [{'text': 'Hello'}]}]) == [
        {'role': 'user', 'text': 'Hi'}, {'role': 'assistant', 'text': 'Hello'}]
