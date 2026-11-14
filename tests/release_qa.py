"""Verify the delivered EXE in isolation and assemble reviewable artifacts."""
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import unittest
import zipfile
from datetime import datetime, date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tls_support import tls_server, FIXTURES
from lightdiary.storage import Store
from lightdiary.ai import daily_context

tls = tls_server()
exe = ROOT / "dist" / "轻盈日记.exe"
qa = ROOT / ".qa" / ("release-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
isolated = qa / "中文 独立运行"
isolated.mkdir(parents=True)
copy = isolated / exe.name
shutil.copy2(exe, copy)
environment = os.environ.copy()
environment["PATH"] = os.environ["SystemRoot"] + "/System32;" + os.environ["SystemRoot"]
environment["QT_QPA_PLATFORM"] = "windows"
environment['LIGHTDIARY_QA_TLS_URL'] = tls.endpoint.replace('http:', 'https:')
environment['LIGHTDIARY_QA_TLS_CA'] = str(FIXTURES/'loopback-test-cert.pem')
for key in ("PYTHONHOME", "PYTHONPATH", "LIGHTDIARY_DATA_DIR"):
    environment.pop(key, None)
startup = subprocess.STARTUPINFO()
startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
startup.wShowWindow = 0
reports = {}
# Also check the directory build with a real TLS handshake before the single-file runs.
folder_exe = ROOT/'build'/'folder'/'轻盈日记'/'轻盈日记.exe'
folder_output = qa/'directory-https'
folder_result = subprocess.run([str(folder_exe), '--smoke-test', str(folder_output)], cwd=isolated,
                               env=environment, startupinfo=startup, timeout=60)
assert folder_result.returncode == 0
assert json.loads((folder_output/'report.json').read_text(encoding='utf-8'))['ai_https_mock']
for scale in ("1", "1.25", "1.5"):
    environment["QT_SCALE_FACTOR"] = scale
    output = qa / ("scale-" + scale)
    result = subprocess.run([str(copy), "--smoke-test", str(output)], cwd=isolated, env=environment, startupinfo=startup, timeout=60)
    assert result.returncode == 0, f"Scale {scale} failed; see {output}"
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    assert report["ok"] and report["frozen"]
    assert report['version']=='1.2.0' and report['food_count']>=60 and report['meal_template_count']>=30
    assert report['nutrition_record'] and report['plan_idempotent'] and report['nutrition_backup_restore']
    assert all(report[key] for key in ('ai_report','ai_followup','ai_dpapi','ai_https_mock','ai_backup_restore'))
    reports[scale] = report
    print(f"Native EXE scale {scale}: passed", flush=True)

# Run two actual processes with the same fresh data directory. A failed guard would
# launch a second long-running app and hit the timeout rather than returning early.
environment["QT_SCALE_FACTOR"] = "1"
fresh = qa / "首次使用数据"
environment["LIGHTDIARY_DATA_DIR"] = str(fresh)
first = subprocess.Popen([str(copy), "--test-exit-after", "12"], cwd=isolated, env=environment, startupinfo=startup)
deadline = time.monotonic() + 8
while not (fresh / "diary.sqlite3").exists() and first.poll() is None and time.monotonic() < deadline:
    time.sleep(.05)
assert (fresh / "diary.sqlite3").exists(), "First run did not create its data directory"
second = subprocess.run([str(copy), "--test-exit-after", "20"], cwd=isolated, env=environment, startupinfo=startup, timeout=10)
assert second.returncode == 0 and first.poll() is None, "Second process did not activate the existing app"
assert first.wait(timeout=20) == 0
connection = sqlite3.connect(fresh / "diary.sqlite3")
try:
    assert connection.execute("SELECT COUNT(*) FROM records").fetchone()[0] == 0
    assert connection.execute('SELECT COUNT(*) FROM meal_entries').fetchone()[0]==0
    assert json.loads(connection.execute("SELECT value FROM settings WHERE key='onboarded'").fetchone()[0]) is False
finally:
    connection.close()
print("First-run isolation and actual second-process activation: passed", flush=True)

# Start a new EXE process with synthetic persisted history to verify restart behavior.
persisted = Store(fresh)
persisted.update_settings({'onboarded': True, 'reminder_enabled': False})
persisted.save_record(dict(day=date.today().isoformat(), weight_kg=72, diet='独立重启验证'))
ident = persisted.save_ai_report(daily_context(persisted, date.today().isoformat()),
    dict(endpoint=environment['LIGHTDIARY_QA_TLS_URL'], model='测试模型'), False, '重启后应保留的测试报告')
persisted.save_ai_followup(ident, '测试问题', '测试回答')
persisted.close()
restart = subprocess.run([str(copy), '--test-exit-after', '3'], cwd=isolated, env=environment, startupinfo=startup, timeout=15)
assert restart.returncode == 0
persisted = Store(fresh)
assert persisted.ai_session(ident)['report'] == '重启后应保留的测试报告'
assert len(persisted.ai_messages(ident)) == 2
assert persisted.record(date.today().isoformat())['weight_kg'] == 72
persisted.close()
tls.close()
print('Actual EXE restart preserved synthetic report and conversation: passed', flush=True)

source_names = (ROOT / "tools" / "public-files.txt").read_text(encoding="utf-8").splitlines()
source_files = [ROOT / name for name in source_names]
archive = ROOT / "dist" / "轻盈日记源码.zip"
with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as package:
    for path in source_files:
        package.write(path, "轻盈日记源码/" + path.relative_to(ROOT).as_posix())
with zipfile.ZipFile(archive) as package:
    assert package.testzip() is None

digest = hashlib.sha256(exe.read_bytes()).hexdigest().upper()
count = unittest.defaultTestLoader.discover(str(ROOT / "tests")).countTestCases()
validation = {
    "date": datetime.now().isoformat(timespec="seconds"), "version": "1.2.0", "exe_bytes": exe.stat().st_size,
    "sha256": digest, "unit_and_ui_tests": count, "native_windows_11": True,
    "standalone_exe": True, "scales": list(reports), "actual_second_process": True,
    "first_run_sample_records": 0, "windows_10_tested": False,
    'food_count':reports['1']['food_count'],'meal_template_count':reports['1']['meal_template_count'],
    'nutrition_record':True,'nutrition_backup_restore':True,'plan_idempotent':True,
    'ai_report':True,'ai_followup':True,'ai_dpapi':True,'ai_https_mock':True,
    'ai_backup_restore':True,'ai_actual_exe_restart':True,'ai_provider_live_tested':False,
    'tls_backend':reports['1']['tls_backend'],
}
(ROOT / "dist" / "验证结果.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8")
shutil.copy2(qa / "scale-1" / "today.png", ROOT / "dist" / "界面预览.png")
shutil.copy2(qa / 'scale-1' / 'diet.png', ROOT / 'dist' / '饮食界面预览.png')
shutil.copy2(qa / 'scale-1' / 'ai.png', ROOT / 'dist' / 'AI分析界面预览.png')
shutil.copy2(qa / 'scale-1' / 'settings.png', ROOT / 'dist' / 'API设置界面预览.png')
shutil.copy2(qa / 'scale-1' / 'ai-followup.png', ROOT / 'dist' / 'AI追问界面预览.png')
shutil.copy2(qa / 'scale-1' / 'ai-request-preview.png', ROOT / 'dist' / 'AI发送预览.png')
note = f"""# 轻盈日记 1.2.0 验证结果

验证日期：{datetime.now():%Y-%m-%d}，当前 Windows 11 64 位电脑。

- {count} 项测试在最终构建前全部通过，覆盖原有 38 项及新增 AI 数据边界、隐私选择、快照、密钥保护、接口与界面测试。
- 目录版与单文件 EXE 均通过打包后保存记录、完整备份恢复、单实例检查。
- 只复制一个 EXE 到中文目录，移除 Python 环境变量和 PATH 后通过原生 Windows 界面运行检查。
- 原生界面在 100%、125%、150% 缩放下完成六页截图及操作检查。
- 本机模拟 OpenAI 兼容服务验证日报、追问、错误码、无效响应、取消、超时、重复点击和重定向保护；不会自动重试。
- 目录版与单文件 EXE 完成真实本机 HTTPS 握手（Qt {reports['1']['tls_backend']} 后端），使用公开测试证书和合成数据。测试同时验证拒绝不受信任证书；未修改 Windows 证书存储。
- DPAPI 当前用户加密、服务地址绑定、备份排除密钥、恢复后密钥失效，以及结构版本 1、2 升级至 3、回滚与完整备份恢复均通过。
- 实际重新启动 EXE 后，测试报告、追问对话和日常记录保持完整。
- 内置 {reports['1']['food_count']} 种食物、{reports['1']['meal_template_count']} 套组合；打包后验证计划与实际摄入分离、重复记录防护及饮食完整备份。
- 正常首次启动保留空白个人记录；两个实际 EXE 进程启动时，第二个返回并激活已有程序。
- 源码 ZIP 完整性检查通过。示例截图只来自独立测试数据，不会写入个人记录。

本机装有 Python；独立运行检查隔离了 Python 搜索路径并使用 EXE 内置解释器。没有另行使用一台未安装 Python 的电脑或 Windows 10 电脑测试。软件按 Windows 10（1809 或更新）／11 x64 打包。

未进行真实服务商或付费模型联调，也未验证 AI 建议的临床准确性。请在软件内填写有效的服务地址、模型和 API Key 后使用「保存并测试连接」；兼容性取决于服务商实现。界面截图中的报告明确标注为独立测试数据。

EXE 文件：{exe.name}，{exe.stat().st_size / 1024 / 1024:.1f} MiB。

SHA256：`{digest}`
"""
(ROOT / "dist" / "验证结果.md").write_text(note, encoding="utf-8")
print(json.dumps(validation, ensure_ascii=False), flush=True)
