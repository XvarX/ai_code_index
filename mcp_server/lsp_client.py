"""
lsp_client.py - LSP实时查询客户端
运行时通过LSP精确查询代码关系
"""

import json
import subprocess
import os
import time


class LSPClient:
    def __init__(self, project_root):
        self.project_root = project_root
        self.process = None
        self.request_id = 0
        self._started = False

    def _ensure_started(self):
        """懒启动，只有真正查询时才启动 pylsp"""
        if self._started:
            return self.process is not None

        self._started = True
        try:
            self.process = subprocess.Popen(
                ['pylsp'],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                cwd=self.project_root,
            )
            # 等待 pylsp 进程启动
            time.sleep(1)
            if self.process.poll() is not None:
                print(f"  pylsp 启动失败，退出码: {self.process.returncode}")
                self.process = None
                return False
            return True
        except FileNotFoundError:
            print("  pylsp 未安装，LSP 功能不可用")
            self.process = None
            return False

    def _read_response(self):
        """读取 LSP 响应，处理各种头部格式"""
        # 读头部直到空行
        headers = {}
        while True:
            line = self.process.stdout.readline()
            if not line or line == b'\r\n':
                break
            if b':' in line:
                key, val = line.decode('ascii', errors='replace').split(':', 1)
                headers[key.strip()] = val.strip()

        length = int(headers.get('Content-Length', '0'))
        if length == 0:
            return None

        body = self.process.stdout.read(length)
        resp = json.loads(body)
        return resp.get('result')

    def _send(self, method, params):
        if not self.process:
            return None
        self.request_id += 1
        msg = {
            'jsonrpc': '2.0',
            'id': self.request_id,
            'method': method,
            'params': params,
        }
        body = json.dumps(msg)
        header = f'Content-Length: {len(body)}\r\n\r\n'
        try:
            self.process.stdin.write(header.encode() + body.encode())
            self.process.stdin.flush()
            return self._read_response()
        except (BrokenPipeError, OSError):
            return None

    def _notify(self, method, params):
        if not self.process:
            return
        msg = {
            'jsonrpc': '2.0',
            'method': method,
            'params': params,
        }
        body = json.dumps(msg)
        header = f'Content-Length: {len(body)}\r\n\r\n'
        try:
            self.process.stdin.write(header.encode() + body.encode())
            self.process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass

    def _open_file(self, filepath):
        full_path = os.path.join(self.project_root, filepath)
        if not os.path.exists(full_path):
            return
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self._notify('textDocument/didOpen', {
            'textDocument': {
                'uri': f'file://{full_path}',
                'languageId': 'python',
                'version': 1,
                'text': content,
            }
        })
        time.sleep(0.5)

    def get_definition(self, file, line, column=0):
        if not self._ensure_started():
            return json.dumps({"error": "LSP 不可用"})
        self._open_file(file)
        full_path = os.path.join(self.project_root, file)
        result = self._send('textDocument/definition', {
            'textDocument': {'uri': f'file://{full_path}'},
            'position': {'line': line - 1, 'character': column},
        })
        return json.dumps(result, ensure_ascii=False, indent=2)

    def get_references(self, file, line):
        if not self._ensure_started():
            return json.dumps({"error": "LSP 不可用"})
        self._open_file(file)
        full_path = os.path.join(self.project_root, file)
        result = self._send('textDocument/references', {
            'textDocument': {'uri': f'file://{full_path}'},
            'position': {'line': line - 1, 'character': 0},
            'context': {'includeDeclaration': True},
        })
        if not result:
            return "未找到引用"
        locations = []
        for ref in result:
            uri = ref.get('uri', '').replace(f'file://{self.project_root}/', '')
            ln = ref.get('range', {}).get('start', {}).get('line', 0) + 1
            locations.append(f"{uri}:{ln}")
        return json.dumps(locations, ensure_ascii=False, indent=2)

    def get_call_chain(self, file, line, direction="outgoing"):
        if not self._ensure_started():
            return json.dumps({"error": "LSP 不可用"})
        return self.get_references(file, line)

    def close(self):
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=3)
            except Exception:
                self.process.kill()
            self.process = None
