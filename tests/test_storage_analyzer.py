# -*- coding: utf-8 -*-
"""storage-analyzer 自动化测试（纯标准库 unittest）。

运行：
  python -m unittest discover -s tests -v

测试只使用临时目录，不读写仓库里的 state/，不改动用户文件。
Windows 回收站真实删除测试默认跳过（避免污染用户回收站），需要验证时运行：
  set SA_REAL_RECYCLE=1 && python -m unittest discover -s tests -v
该项会在回收站留下 sa_recycle_test_*、测试 缓存 *、empty_dir_*、
nonempty dir *、readonly_* 等小测试项。
"""
import http.client
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, SCRIPTS)

import orphan  # noqa: E402
import registry  # noqa: E402
import report_util  # noqa: E402
import rules  # noqa: E402
import scan  # noqa: E402
import server  # noqa: E402
import statefile  # noqa: E402


def _bump_process(path, n):
    """跨进程锁测试的 worker；必须是模块级函数，Windows spawn 才能 pickle。"""
    for _ in range(n):
        with statefile.locked(path):
            cur = statefile.load_json(path, {"n": 0})
            cur["n"] += 1
            statefile.save_json(path, cur)


def write_csv(path, rows):
    """写带 BOM 的 Everything 风格 CSV，顺便验证读取端的 BOM 兼容。"""
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        for p, sz in rows:
            f.write('"%s",%d\n' % (p, sz))


def run_script(name, *args):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, os.path.join(SCRIPTS, name), *args],
        capture_output=True, text=True, encoding="utf-8", timeout=180, env=env)


class ReportUtilTests(unittest.TestCase):
    def test_json_for_script_escapes_closing_tag(self):
        blob = report_util.json_for_script({"name": "</script><script>alert(1)"})
        self.assertNotIn("</script>", blob)
        self.assertIn("<\\/script>", blob)
        self.assertEqual(json.loads(blob)["name"], "</script><script>alert(1)")

    def test_template_escapes_quote_and_gates_rm(self):
        with open(os.path.join(ROOT, "assets", "report_template.html"), encoding="utf-8") as f:
            tpl = f.read()
        self.assertIn("'&#39;'", tpl)
        self.assertIn("DELETE.allow_rm", tpl)
        self.assertIn("本次服务未启用永久删除", tpl)


class RulesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sa_rules_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.csv = os.path.join(self.tmp, "scan_C.csv")
        base = r"C:\sandbox"
        write_csv(self.csv, [
            (base + r"\App\plugins\a.zip", 5 * 2**20),
            (base + r"\App\plugins\b_download", 3 * 2**20),
            (base + r"\App\Code Cache\js.bin", 1 * 2**20),
            (base + r"\App\Cache\blob.bin", 2 * 2**20),
            (base + r"\App\crashdumps\crash.dmp", 4 * 2**20),
            (base + r"\App\dumps\data.bin", 2 * 2**20),
            (base + r"\App\bin\2.6.9\app.exe", 1 * 2**20),
            (base + r"\App\bin\2.6.10\app.exe", 1 * 2**20),
            (base + r"\App\bin\2.6.10-beta\app.exe", 1 * 2**20),
            (base + r"\App\logs\huge.log", 30 * 2**20),
            (base + r"\App\logs\small.log", 1024),
        ])

    def test_groups_review_and_version_order(self):
        r = run_script("rules.py", "--csv", self.csv, "--min-mb", "1")
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(r.stdout)
        green = data["green_candidates"]
        review = data["review_candidates"]

        plugin = [g for g in green if g["rule"] == "plugins_zip_cache"]
        self.assertEqual(len(plugin), 1, "带 BOM 的 CSV 不应把同目录拆成两组")
        self.assertTrue(plugin[0]["path"].startswith(r"C:\sandbox\App\plugins"))
        self.assertEqual(len(plugin[0]["files"]), 2)

        self.assertTrue(any(g["rule"] == "crash_dumps" for g in green))
        self.assertFalse(any(g["path"].endswith(r"\Cache") for g in green),
                         "宽泛 cache 目录不能直接判绿")
        self.assertTrue(any(g["rule"] == "broad_cache_name" for g in review))
        self.assertTrue(any(g["rule"] == "big_log_file" for g in review))
        self.assertTrue(any(g["rule"] == "ambiguous_dumps" for g in review))

        mv = data["multi_version_groups"][0]
        self.assertEqual(mv["keep"], "2.6.10", "同版本稳定版应优先于 beta")
        self.assertEqual(mv["confidence"], "needs_review")


class OrphanTests(unittest.TestCase):
    def test_match_installed_is_strict(self):
        self.assertEqual(orphan.match_installed("qq", "qq", {"qqmusic"}), (None, None))
        self.assertEqual(orphan.match_installed("wechatapp", "wechatapp", {"wechat"}),
                         ("contains", "wechat"))
        self.assertEqual(orphan.match_installed("qianwen", "qianwen", {"tongyiqianwen"}),
                         ("contains", "tongyiqianwen"))
        self.assertEqual(orphan.match_installed("kiro", "kiro", {"kiro"}),
                         ("alias", "kiro"))

    def test_csv_tree_handles_bom(self):
        tmp = tempfile.mkdtemp(prefix="sa_orphan_")
        self.addCleanup(shutil.rmtree, tmp, True)
        csv = os.path.join(tmp, "scan_C.csv")
        write_csv(csv, [(os.path.join(tmp, "Ghost", "a.bin"), 2**20)])
        tree = orphan.load_csv_tree(csv)
        self.assertEqual(tree.get(os.path.join(tmp, "Ghost")), 2**20)
        self.assertFalse(any(k.startswith('"') for k in tree), "BOM 不应残留引号")

    def test_outputs_evidence_chain_and_caps_confidence(self):
        tmp = tempfile.mkdtemp(prefix="sa_orphan_")
        self.addCleanup(shutil.rmtree, tmp, True)
        home = os.path.join(tmp, "home")
        local = os.path.join(home, "AppData", "Local")
        roaming = os.path.join(home, "AppData", "Roaming")
        ghost = os.path.join(roaming, "GhostRoam")
        os.makedirs(ghost)
        f = os.path.join(ghost, "blob.bin")
        with open(f, "wb") as fh:
            fh.write(b"x" * 2048)
        old = 1_000_000_000
        os.utime(f, (old, old))
        os.utime(ghost, (old, old))
        csv = os.path.join(tmp, "scan_C.csv")
        write_csv(csv, [(f, 30 * 2**20)])

        originals = (orphan.U, orphan.LOCAL, orphan.ROAMING, orphan.collect_installed_names)
        orphan.U, orphan.LOCAL, orphan.ROAMING = home, local, roaming
        orphan.collect_installed_names = lambda: (set(), [
            {"source": "卸载注册表", "status": "denied", "names": 0, "note": "denied"},
        ])
        self.addCleanup(setattr, orphan, "collect_installed_names", originals[3])
        self.addCleanup(setattr, orphan, "ROAMING", originals[2])
        self.addCleanup(setattr, orphan, "LOCAL", originals[1])
        self.addCleanup(setattr, orphan, "U", originals[0])

        argv = sys.argv
        sys.argv = ["orphan.py", "--csv", csv, "--min-mb", "1"]
        self.addCleanup(setattr, sys, "argv", argv)
        out = io.StringIO()
        with redirect_stdout(out):
            orphan.main()
        data = json.loads(out.getvalue())
        self.assertEqual(data["summary"]["count"], 1)
        o = data["orphans"][0]
        self.assertIn("confidence_basis", o)
        self.assertIn("sources_checked", o["evidence"])
        self.assertIn("卸载注册表", o["evidence"]["sources_incomplete"])
        self.assertEqual(o["confidence"], "medium", "证据不完整时高置信度必须降级")
        self.assertEqual(o["name_checked"]["normalized"], "ghostroam")


class StatefileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sa_state_")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_atomic_save_and_load(self):
        p = os.path.join(self.tmp, "x.json")
        statefile.save_json(p, {"a": 1})
        self.assertEqual(statefile.load_json(p, {}), {"a": 1})
        self.assertEqual(statefile.load_json(os.path.join(self.tmp, "none.json"), {"d": 2}),
                         {"d": 2})

    def test_corrupt_file_quarantined(self):
        p = os.path.join(self.tmp, "x.json")
        with open(p, "w", encoding="utf-8") as f:
            f.write("{broken")
        self.assertEqual(statefile.load_json(p, {"ok": True}), {"ok": True})
        names = os.listdir(self.tmp)
        self.assertTrue(any(n.startswith("x.json.corrupt-") for n in names))
        self.assertFalse(os.path.exists(p))

    def test_lock_serializes_threads(self):
        p = os.path.join(self.tmp, "c.json")
        statefile.save_json(p, {"n": 0})

        def bump():
            for _ in range(50):
                with statefile.locked(p):
                    cur = statefile.load_json(p, {"n": 0})
                    cur["n"] += 1
                    statefile.save_json(p, cur)

        threads = [threading.Thread(target=bump) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(statefile.load_json(p, {})["n"], 200)

    def test_lock_is_reentrant(self):
        p = os.path.join(self.tmp, "r.json")
        with statefile.locked(p):
            with statefile.locked(p):
                statefile.save_json(p, {"ok": True})
        self.assertTrue(statefile.load_json(p, {})["ok"])

    def test_lock_serializes_processes(self):
        import multiprocessing
        p = os.path.join(self.tmp, "p.json")
        statefile.save_json(p, {"n": 0})
        ctx = multiprocessing.get_context("spawn")
        procs = [ctx.Process(target=_bump_process, args=(p, 15)) for _ in range(3)]
        for proc in procs:
            proc.start()
        for proc in procs:
            proc.join(60)
            self.assertEqual(proc.exitcode, 0)
        self.assertEqual(statefile.load_json(p, {})["n"], 45)


class SchemaCompatTests(unittest.TestCase):
    def test_normalize_reg_fills_missing_fields(self):
        reg = registry.normalize_reg({"dirs": {"C:\\x": {"size": None, "unexpected": 1}}})
        ent = reg["dirs"]["C:\\x"]
        self.assertEqual(ent["size"], 0)
        self.assertIsNone(ent["tier"])
        self.assertFalse(ent["deleted"])
        self.assertEqual(ent["unexpected"], 1, "未知字段应保留，不能静默丢弃")

    def test_normalize_reg_rejects_wrong_types(self):
        reg = registry.normalize_reg({"dirs": ["not-a-dict"]})
        self.assertEqual(reg["dirs"], {})

    @unittest.skipUnless(sys.platform.startswith("win"), "apps.py 依赖 winreg")
    def test_normalize_store_fills_missing_fields(self):
        import apps
        store = apps.normalize_store({"apps": {"k": {"size_bytes": "bad",
                                                    "data_paths": "bad"}}})
        ent = store["apps"]["k"]
        self.assertEqual(ent["size_bytes"], 0)
        self.assertEqual(ent["data_paths"], [])
        self.assertFalse(ent["reviewed"])


class ServerSecurityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sa_server_")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_outside_root_rejected(self):
        root = os.path.join(self.tmp, "root")
        other = os.path.join(self.tmp, "other")
        os.makedirs(root)
        os.makedirs(other)
        rp = os.path.realpath(other)
        self.assertEqual(server.validate_target(rp, {rp}, "trash", roots=[root]), "路径越界")

    def test_sensitive_home_rejected(self):
        self.assertIn("敏感", server.validate_target(
            server.HOME, {server.HOME}, "trash", roots=[server.HOME]))

    def test_not_in_allowlist_rejected(self):
        p = os.path.join(self.tmp, "a")
        os.makedirs(p)
        self.assertEqual(server.validate_target(os.path.realpath(p), set(), "trash",
                                                roots=[self.tmp]), "路径不在白名单")

    @unittest.skipUnless(sys.platform.startswith("win"), "junction 仅 Windows")
    def test_junction_deletes_link_only(self):
        target = os.path.join(self.tmp, "target")
        os.makedirs(target)
        keep = os.path.join(target, "keep.txt")
        with open(keep, "w", encoding="utf-8") as f:
            f.write("keep")
        link = os.path.join(self.tmp, "link")
        r = subprocess.run(["cmd", "/c", "mklink", "/J", link, target],
                           capture_output=True, text=True)
        if r.returncode != 0:
            self.skipTest("当前环境无法创建 junction：%s" % (r.stderr or r.stdout))
        self.assertTrue(server.is_reparse_point(link))
        server.hard_delete(link)
        self.assertFalse(os.path.lexists(link))
        self.assertTrue(os.path.exists(keep), "不能递归删掉 junction 指向的真实目录")


class ServerHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sa_http_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.saved = (server.DATA, server.TPL, server.RM_ALLOW, server.TRASH_ALLOW,
                      server.OPEN_ALLOW, server.ALLOW_RM, server.STATE_DIR,
                      server.AUDIT_FILE, server.ROOTS)
        server.DATA = {"green": [], "yellow": [], "red": []}
        server.TPL = '<html>__REPORT_DATA__|__DELETE_CONFIG__</html>'
        server.RM_ALLOW = set()
        server.TRASH_ALLOW = set()
        server.OPEN_ALLOW = set()
        server.ALLOW_RM = False
        server.STATE_DIR = self.tmp
        server.AUDIT_FILE = os.path.join(self.tmp, "audit.jsonl")
        # 测试沙箱在 %TEMP% 下（Windows 属于 HOME，Linux 不属于），统一把根设为沙箱
        server.ROOTS = [os.path.realpath(self.tmp)]

    def tearDown(self):
        (server.DATA, server.TPL, server.RM_ALLOW, server.TRASH_ALLOW,
         server.OPEN_ALLOW, server.ALLOW_RM, server.STATE_DIR,
         server.AUDIT_FILE, server.ROOTS) = self.saved

    def post(self, payload, host=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Content-Type": "application/json"}
        if host:
            headers["Host"] = host
        conn.request("POST", "/action", json.dumps(payload), headers)
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        conn.close()
        return resp.status, json.loads(body)

    def get(self, path="/"):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        conn.close()
        return resp.status, body

    def make_file(self, name="cache.bin"):
        p = os.path.join(self.tmp, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write("x")
        return p

    def test_get_renders_token_and_rm_flag(self):
        code, body = self.get()
        self.assertEqual(code, 200)
        self.assertIn(server.TOKEN, body)
        self.assertIn('"allow_rm": false', body)

    def test_bad_token_and_host_rejected(self):
        code, data = self.post({"token": "wrong", "mode": "open", "paths": []})
        self.assertEqual(code, 403)
        code, data = self.post({"token": server.TOKEN, "mode": "open",
                                "paths": [self.tmp]}, host="evil.example")
        self.assertEqual(code, 403)
        self.assertIn("host", data["error"])

    def test_rm_disabled_by_default(self):
        p = self.make_file()
        server.RM_ALLOW = {os.path.realpath(p)}
        code, data = self.post({"token": server.TOKEN, "mode": "rm", "paths": [p]})
        self.assertEqual(code, 403)
        self.assertTrue(os.path.exists(p))
        self.assertIn("--allow-rm", data["error"])

    def test_rm_enabled_deletes_and_audits(self):
        p = self.make_file()
        server.RM_ALLOW = {os.path.realpath(p)}
        server.ALLOW_RM = True
        code, data = self.post({"token": server.TOKEN, "mode": "rm", "paths": [p]})
        self.assertEqual(code, 200)
        self.assertTrue(data["ok"])
        self.assertFalse(os.path.exists(p))
        with open(server.AUDIT_FILE, encoding="utf-8") as f:
            self.assertIn('"mode": "rm"', f.read())

    def test_missing_path_reported_per_item(self):
        p = self.make_file()
        missing = os.path.join(self.tmp, "already-gone.bin")
        server.RM_ALLOW = {os.path.realpath(p), os.path.realpath(missing)}
        server.ALLOW_RM = True
        code, data = self.post({"token": server.TOKEN, "mode": "rm", "paths": [p, missing]})
        self.assertEqual(code, 200)
        statuses = {r["path"]: r.get("status") for r in data["results"]}
        self.assertEqual(statuses[p], "deleted")
        self.assertEqual(statuses[missing], "missing")

    def test_path_not_in_allowlist_rejected(self):
        p = self.make_file()
        code, data = self.post({"token": server.TOKEN, "mode": "trash", "paths": [p]})
        self.assertEqual(code, 403)
        self.assertTrue(os.path.exists(p))

    def test_missing_token_rejected(self):
        p = self.make_file()
        server.TRASH_ALLOW = {os.path.realpath(p)}
        code, data = self.post({"mode": "trash", "paths": [p]})
        self.assertEqual(code, 403)
        self.assertIn("token", data["error"])
        self.assertTrue(os.path.exists(p))

    def test_unknown_mode_rejected(self):
        p = self.make_file()
        code, data = self.post({"token": server.TOKEN, "mode": "delete", "paths": [p]})
        self.assertEqual(code, 400)
        self.assertIn("未知操作", data["error"])
        self.assertTrue(os.path.exists(p))

    def test_get_action_not_allowed(self):
        p = self.make_file()
        server.RM_ALLOW = {os.path.realpath(p)}
        server.ALLOW_RM = True
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", "/action")
        resp = conn.getresponse()
        resp.read()
        conn.close()
        self.assertEqual(resp.status, 404)
        self.assertTrue(os.path.exists(p), "GET 不得触发任何删除")

    def test_dotdot_traversal_rejected(self):
        allowed = os.path.join(self.tmp, "allowed")
        os.makedirs(allowed)
        secret = os.path.join(self.tmp, "secret.txt")
        with open(secret, "w", encoding="utf-8") as f:
            f.write("keep")
        server.RM_ALLOW = {os.path.realpath(allowed)}
        server.ALLOW_RM = True
        payload = os.path.join(allowed, "..", "secret.txt")
        code, data = self.post({"token": server.TOKEN, "mode": "rm", "paths": [payload]})
        self.assertEqual(code, 403)
        self.assertTrue(os.path.exists(secret))

    def test_trash_failure_and_cancel_reported(self):
        original = server.move_to_trash
        self.addCleanup(setattr, server, "move_to_trash", original)
        for index, msg in enumerate(("SHFileOperation failed (code 5)",
                                     "回收站操作被系统取消")):
            with self.subTest(msg=msg):
                p = self.make_file("fail_%d_%d.bin" % (os.getpid(), index))
                server.TRASH_ALLOW = {os.path.realpath(p)}

                def boom(path, _msg=msg):
                    raise OSError(_msg)

                server.move_to_trash = boom
                code, data = self.post({"token": server.TOKEN, "mode": "trash",
                                        "paths": [p]})
                self.assertEqual(code, 200, data)
                self.assertFalse(data["ok"])
                self.assertEqual(data["failed"], 1)
                self.assertIn(msg, data["results"][0]["error"])
                self.assertTrue(os.path.exists(p), "回收站失败不得降级为永久删除")

    def test_batch_audit_summary_fields(self):
        p1 = self.make_file("batch_a.bin")
        p2 = self.make_file("batch_b.bin")
        server.RM_ALLOW = {os.path.realpath(p1), os.path.realpath(p2)}
        server.ALLOW_RM = True
        code, data = self.post({"token": server.TOKEN, "mode": "rm",
                                "paths": [p1, p2]})
        self.assertEqual(code, 200, data)
        with open(server.AUDIT_FILE, encoding="utf-8") as f:
            lines = [json.loads(x) for x in f if x.strip()]
        batch = [x for x in lines if x.get("action") == "batch"]
        self.assertEqual(len(batch), 1, lines)
        self.assertEqual(batch[0]["count"], 2)
        self.assertEqual(batch[0]["ok_count"], 2)
        self.assertEqual(batch[0]["failed"], 0)
        self.assertEqual(batch[0]["risk"], "high")
        self.assertEqual(batch[0]["mode"], "rm")

    @unittest.skipUnless(sys.platform.startswith("win"), "回收站仅 Windows")
    @unittest.skipUnless(os.environ.get("SA_REAL_RECYCLE") == "1",
                         "真实回收站测试会污染用户回收站；设 SA_REAL_RECYCLE=1 才执行")
    def test_real_recycle_bin_mixed_batch(self):
        """真实回收站：普通文件、中文+空格、空目录、非空目录、只读文件、批量。"""
        plain = self.make_file("sa_recycle_test_%d.txt" % os.getpid())
        cn = self.make_file("测试 缓存 %d.txt" % os.getpid())
        empty_dir = os.path.join(self.tmp, "empty_dir_%d" % os.getpid())
        os.makedirs(empty_dir)
        full_dir = os.path.join(self.tmp, "nonempty dir %d" % os.getpid())
        os.makedirs(os.path.join(full_dir, "sub"))
        with open(os.path.join(full_dir, "sub", "x.bin"), "wb") as f:
            f.write(b"x" * 1024)
        readonly = self.make_file("readonly_%d.txt" % os.getpid())
        os.chmod(readonly, stat.S_IREAD)
        paths = [plain, cn, empty_dir, full_dir, readonly]
        server.TRASH_ALLOW = {os.path.realpath(p) for p in paths}
        code, data = self.post({"token": server.TOKEN, "mode": "trash", "paths": paths})
        self.assertEqual(code, 200, data)
        self.assertTrue(data["ok"], data)
        self.assertEqual(data["failed"], 0)
        for p in paths:
            self.assertFalse(os.path.exists(p), "%s 仍在原位置" % p)


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sa_scan_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.sandbox = os.path.join(self.tmp, "sandbox")
        os.makedirs(os.path.join(self.sandbox, "app", "cache"))
        for rel, size in [("app/cache/a.bin", 2 * 2**20),
                          ("app/b.log", 1024),
                          ("top.txt", 10)]:
            with open(os.path.join(self.sandbox, rel), "wb") as f:
                f.write(b"x" * size)
        self.csv = os.path.join(self.tmp, "scan_C.csv")

    def test_walk_export_and_combined_pass(self):
        stats = scan.walk_export_csv(self.sandbox, self.csv)
        self.assertEqual(stats["files"], 3)
        rows = list(scan.iter_rows(self.csv))
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(p.startswith(self.sandbox) for p, _ in rows))
        res = scan.combined_pass(self.csv, self.sandbox, min_dir_mb=1, big_mb=1,
                                 cache_mb=1, updater_mb=1, ver_mb=1, top=10)
        self.assertEqual(res["count"], 3)
        self.assertEqual(res["total"], 2 * 2**20 + 1024 + 10)

    def test_scan_windows_coverage_contract(self):
        original_walk = scan.walk_export_csv
        originals = {name: getattr(scan, name) for name in (
            "find_es", "find_wiztree", "list_drives_windows",
            "system_info_windows", "dir_size_bytes", "running_apps")}
        scan.find_es = lambda: None
        scan.find_wiztree = lambda: None
        scan.list_drives_windows = lambda: [{"name": "C:\\"}]
        scan.system_info_windows = lambda: {"os": "Windows-test", "disks": []}
        scan.dir_size_bytes = lambda p: 0
        scan.running_apps = lambda: []
        scan.walk_export_csv = lambda drive, out: original_walk(self.sandbox, out)
        for name, fn in originals.items():
            self.addCleanup(setattr, scan, name, fn)
        self.addCleanup(setattr, scan, "walk_export_csv", original_walk)

        system, groups, coverage, artifacts = scan.scan_windows({
            "source": "walk", "drives": ["C:\\"], "tmpdir": self.tmp,
            "min_dir_mb": 1, "big_mb": 1, "cache_mb": 1, "updater_mb": 1,
            "ver_mb": 1, "top": 10,
        })
        self.assertEqual(coverage["method"], "walk")
        self.assertEqual(coverage["files_scanned"], 3)
        self.assertTrue(coverage["complete"])
        self.assertFalse(coverage["partial"])
        for key in ("drives_detail", "fallback_reasons", "denied_dirs", "errors",
                    "partial", "complete"):
            self.assertIn(key, coverage)
        self.assertEqual(coverage["drives_detail"][0]["source"], "walk")
        self.assertIn("drive_C", groups)

    def _patch_scan(self, **overrides):
        names = ("find_es", "find_wiztree", "list_drives_windows",
                 "system_info_windows", "dir_size_bytes", "running_apps",
                 "walk_export_csv", "wiztree_export_csv")
        originals = {n: getattr(scan, n) for n in names}
        for n, fn in overrides.items():
            setattr(scan, n, fn)
        for n, fn in originals.items():
            self.addCleanup(setattr, scan, n, fn)
        scan.list_drives_windows = lambda: [{"name": "C:\\"}]
        scan.system_info_windows = lambda: {"os": "Windows-test", "disks": []}
        scan.dir_size_bytes = lambda p: 0
        scan.running_apps = lambda: []
        scan.find_es = lambda: None

    def test_wiztree_without_admin_records_caveat(self):
        def fake_wiz(wz, drive, out, admin=False):
            scan.walk_export_csv(self.sandbox, out)
            return True

        self._patch_scan(find_wiztree=lambda: "wiztree64.exe",
                         wiztree_export_csv=fake_wiz)
        _sys, _groups, coverage, _artifacts = scan.scan_windows({
            "source": "wiztree", "drives": ["C:\\"], "tmpdir": self.tmp,
            "min_dir_mb": 1, "big_mb": 1, "cache_mb": 1, "updater_mb": 1,
            "ver_mb": 1, "top": 10,
        })
        self.assertEqual(coverage["method"], "wiztree")
        self.assertTrue(coverage["limited"])
        self.assertTrue(coverage["partial"])
        self.assertFalse(coverage["complete"])
        self.assertTrue(any("WizTree" in c for c in coverage["caveats"]))
        self.assertTrue(coverage["drives_detail"][0]["limited"])
        self.assertTrue(coverage["drives_detail"][0]["caveats"])

    def test_zero_files_with_used_disk_is_suspect(self):
        self._patch_scan(
            walk_export_csv=lambda drive, out: {"files": 0, "denied": 0, "errors": []})
        original_disk = scan.shutil.disk_usage
        self.addCleanup(setattr, scan.shutil, "disk_usage", original_disk)
        scan.shutil.disk_usage = lambda p: type("U", (), {"used": 10 * 2**30})()
        _sys, _groups, coverage, _artifacts = scan.scan_windows({
            "source": "walk", "drives": ["C:\\"], "tmpdir": self.tmp,
            "min_dir_mb": 1, "big_mb": 1, "cache_mb": 1, "updater_mb": 1,
            "ver_mb": 1, "top": 10,
        })
        self.assertTrue(coverage["suspect"])
        self.assertTrue(coverage["partial"])
        self.assertFalse(coverage["complete"])
        self.assertEqual(coverage["files_scanned"], 0)
        self.assertTrue(any("不可信" in c for c in coverage["caveats"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
