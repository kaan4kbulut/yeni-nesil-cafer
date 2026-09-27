"""Yönetici döngüsü testleri: plan kararı, planın ayrıştırılması, plan → yap → doğrula → düzelt akışı.

Model çağrıları sahte: `specialists.ask` sıradaki hazır cevabı döndürür, ajan araç çalıştırmış gibi davranır.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))
_GECICI = tempfile.mkdtemp(prefix="yeni-nesil-cafer-test-")
os.environ["XDG_CONFIG_HOME"] = str(Path(_GECICI) / "ayar")
os.environ["XDG_DATA_HOME"] = str(Path(_GECICI) / "veri")

from asistan import manager  # noqa: E402
from asistan.agent import PROGRAM, _clean  # noqa: E402


class PlanKarari(unittest.TestCase):
    def test_basit_istekler_plansiz(self):
        for text in ("telegram aç", "merhaba nasılsın", "bugün hava nasıl?", "rapor.xlsx dosyasını oluştur",
                     "📈 gelişim raporu: oluştur ve yaz"):
            self.assertFalse(manager.needs_plan(text), text)

    def test_cok_parcali_isler_planli(self):
        for text in ("satis.csv'yi oku, bir grafik oluştur ve sonucu rapor.docx olarak yaz",
                     "Şunları yap:\n1. klasördeki resimleri küçült\n2. hepsini bir zip dosyasına kopyala",
                     "▶ Onaylıyorum, yap: «verileri temizle ve grafiğini çiz»",
                     "a.txt dosyasına 3 meyve yaz, sonra satırları sayıp b.txt'ye yaz"):
            self.assertTrue(manager.needs_plan(text), text)

    def test_plan_ayristirma(self):
        cevap = 'Tamam: ```json\n{"steps": [{"title": "Oku", "do": "veriyi oku", "done_when": "okundu"},' \
                ' {"title": "", "do": "grafik çiz", "done_when": ""}, {"title": "boş", "do": ""}]}\n```'
        steps = manager.clean_steps(manager.parse_json(cevap))
        self.assertEqual([s["do"] for s in steps], ["veriyi oku", "grafik çiz"])
        self.assertEqual(steps[1]["title"], "grafik çiz")  # başlıksız adımın başlığı talimatı olur
        self.assertTrue(all(s["status"] == "pending" for s in steps))
        many = {"steps": [{"title": str(i), "do": f"iş {i}", "done_when": ""} for i in range(9)]}
        self.assertEqual(len(manager.clean_steps(many)), manager.MAX_PLAN_STEPS)
        self.assertEqual(manager.clean_steps(None), [])

    def test_ic_alanlar_saglayiciya_gitmez(self):
        msgs = [{"role": "user", "content": "x", "_plan": [{"title": "a"}]},
                {"role": "user", PROGRAM: True, "content": "adım"}]
        self.assertEqual(_clean(msgs), [{"role": "user", "content": "x"}, {"role": "user", "content": "adım"}])


class _Olaylar:
    def __init__(self):
        self.plans, self.steps, self.text = [], [], ""

    def on_plan(self, steps): self.plans.append(None if steps is None else [dict(s) for s in steps])
    def on_step(self, i, status, note): self.steps.append((i, status))
    def on_text(self, delta): self.text += delta
    def on_tool_start(self, *a): pass
    def on_tool_end(self, *a): pass
    def is_cancelled(self): return False


class _SahteAjan:
    """Agent'ın yöneticinin kullandığı kısmı. `isler`: her run çağrısında çalıştırılacak (araç, sonuç, hata)."""

    def __init__(self, root: str, isler: list):
        self.profile, self.gate_actions, self.no_tools = None, False, False
        self.tool_specs = [{"name": "run_python"}, {"name": "write_file"}]
        self.settings = mock.Mock(ollama_url="", ollama_model="")
        self.toolbox = mock.Mock(root=root)
        self.connections, self.cb, self._provider = [], _Olaylar(), "claude"
        self.security_stop, self.focus, self.user_text = False, "", ""
        self.check_nudges, self.verified, self.gave_up = 0, False, False
        self.isler, self.cagrilar = list(isler), []

    def _model(self): return "sahte"
    def _check_cancel(self): pass

    def run(self, provider, messages, user_text, step=""):
        messages.append({"role": "user", PROGRAM: True, "content": step} if step else
                        {"role": "user", "content": user_text})
        self.cagrilar.append((step, self.focus))
        for name, result, error in (self.isler.pop(0) if self.isler else []):
            self.cb.on_tool_start("id", name, {"code": "x"})
            self.cb.on_tool_end("id", result, error)
        self.cb.on_text("yaptım")
        messages.append({"role": "assistant", "content": "yaptım"})


def _cevaplar(*items):
    it = iter(json.dumps(x) for x in items)
    return mock.patch.object(manager.specialists, "ask", side_effect=lambda *a, **k: next(it))


PLAN = {"steps": [{"title": "Oku", "do": "veriyi oku", "done_when": "okundu"},
                  {"title": "Çiz", "do": "grafik.png çiz", "done_when": "grafik.png var"}]}
ISTEK = "veriyi oku ve grafik oluştur"


class YoneticiDongusu(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(dir=_GECICI)

    def test_plan_yap_dogrula(self):
        ajan = _SahteAjan(self.root, [[("run_python", "ok", False)], [("run_python", "ok", False)], []])
        messages = []
        with _cevaplar(PLAN, {"done": True, "missing": ""}, {"done": True, "missing": ""}):
            manager.Manager(ajan).run("claude", messages, ISTEK)
        self.assertEqual(messages[0]["content"], ISTEK)  # kullanıcının isteği gerçek kullanıcı mesajı
        self.assertEqual([s["status"] for s in messages[0]["_plan"]], ["done", "done"])  # plan kaydedildi
        self.assertEqual(len(ajan.cagrilar), 3)  # 2 adım + son özet
        self.assertEqual(ajan.cagrilar[0][1], "veriyi oku")  # adımın "bitti mi" denetimi o adıma bakar
        self.assertIn("step 2/2", ajan.cagrilar[1][0])
        self.assertEqual(ajan.focus, "")
        self.assertIsNone(ajan.cb.plans[0])  # önce "plan çıkarılıyor"
        self.assertEqual(ajan.cb.steps, [(0, "running"), (0, "checking"), (0, "done"),
                                         (1, "running"), (1, "checking"), (1, "done")])

    def test_eksik_adim_bir_kez_duzelttirilir(self):
        ajan = _SahteAjan(self.root, [[("run_python", "ok", False)], [("write_file", "ok", False)],
                                      [("write_file", "ok", False)], []])
        with _cevaplar(PLAN, {"done": True, "missing": ""}, {"done": False, "missing": "grafik.png yok"},
                       {"done": True, "missing": ""}):
            manager.Manager(ajan).run("claude", [], ISTEK)
        self.assertIn((1, "fixing"), ajan.cb.steps)
        self.assertEqual(ajan.cb.steps[-1], (1, "done"))
        self.assertIn("grafik.png yok", ajan.cagrilar[2][0])  # düzeltme talimatında eksik yazıyor

    def test_hepsi_hata_verirse_model_sorulmadan_basarisiz(self):
        hata = [("run_python", "Error: Traceback …\nNameError: x", True)]
        ajan = _SahteAjan(self.root, [hata, hata, [("run_python", "ok", False)], []])
        with _cevaplar(PLAN, {"done": True, "missing": ""}):  # yalnızca 2. adımın denetimi modele gider
            manager.Manager(ajan).run("claude", [], ISTEK)
        self.assertIn((0, "fixing"), ajan.cb.steps)
        self.assertIn((0, "failed"), ajan.cb.steps)
        self.assertEqual(ajan.cb.steps[-1], (1, "done"))
        self.assertIn("✗", ajan.cagrilar[-1][0])  # son özet başarısız adımı biliyor

    def test_tek_adimlik_plan_plansiz_calisir(self):
        ajan = _SahteAjan(self.root, [])
        messages = []
        with _cevaplar({"steps": [{"title": "Yap", "do": "yap", "done_when": ""}]}):
            manager.Manager(ajan).run("claude", messages, ISTEK)
        self.assertEqual(ajan.cagrilar, [("", "")])
        self.assertNotIn("_plan", messages[0])
        self.assertEqual(ajan.cb.plans, [None, []])

    def test_basit_istekte_model_hic_sorulmaz(self):
        ajan = _SahteAjan(self.root, [])
        with mock.patch.object(manager.specialists, "ask") as ask:
            manager.Manager(ajan).run("claude", [], "telegram aç")
        ask.assert_not_called()
        self.assertEqual(ajan.cb.plans, [])


class GrupYoneticisi(unittest.TestCase):
    """Grup çalışmasında (work.py) yönetici plan, kontrol ve rapor yazar: "iş bitmedi, araçla yap" dürtülmez."""

    def test_yonetici_durtulmez_isci_durtulur(self):
        from asistan.agent import Agent
        from asistan.config import Settings
        from asistan.work import Task, TeamRunner

        s = Settings(workspace=str(Path(_GECICI) / "is"))
        task = Task(title="Kareler", goal="kareler.txt dosyasına 1-10 karelerini yaz", provider="ollama",
                    model="qwen2.5:14b", folder=str(Path(_GECICI) / "is" / "kareler"))
        runner = TeamRunner(task, s, [], [], mock.MagicMock())
        yonetici, _ = runner._manager(mock.MagicMock())
        self.assertFalse(yonetici.nudges)
        yonetici.user_text = "Write the final report. 1. Sonuç 2. Önerim"
        rapor = "## Sonuç\n1. kareler.txt oluşturuldu\n2. Dosyayı aç"
        self.assertIsNone(yonetici._unfinished_nudge([], rapor, True, 1, {}))
        isci = Agent(s, mock.MagicMock())
        self.assertTrue(isci.nudges)
        # olmayan araç: hata, elindeki araçları söyler (aynı aracı tekrar tekrar denemesin)
        hata, is_error = yonetici._execute_tool("1", "run_python", {"code": "print(1)"})
        self.assertTrue(is_error)
        self.assertIn("Do not call it again", hata)
        self.assertIn("ask_specialist", hata)


if __name__ == "__main__":
    unittest.main()
