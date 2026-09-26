#!/usr/bin/env python3
# 通过Hermes发送消息到Telegram
import sys
import subprocess

def send(text):
    # 使用Hermes send_message 发送消息
    cmd = [
        'hermes',
        'send_message',
        '-a',
        'send',
        '-m',
        text,
        '-t',
        'telegram'
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            print(f'[hermes] 发送失败: {result.stderr}', file=sys.stderr)
    except Exception as e:
        print(f'[hermes] 执行异常: {e}', file=sys.stderr)

if __name__ == '__main__':
    text = sys.stdin.read()
    if text.strip():
        send(text)