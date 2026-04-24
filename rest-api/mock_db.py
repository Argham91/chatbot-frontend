mock_messages = [
    {"id": 1, "text": "Hello, how can I help you?", "role": "bot"},
    {"id": 2, "text": "Show production data", "role": "user"}
]

def get_messages():
    return mock_messages

def add_message(message):
    mock_messages.append(message)
    return message