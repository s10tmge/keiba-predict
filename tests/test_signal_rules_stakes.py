"""
tests/test_signal_rules_stakes.py - 重賞スコアリングロジックのユニットテスト

DB不要。実行: python -m unittest tests.test_signal_rules_stakes -v
"""

import unittest

from analysis.signal_rules_stakes import (
    _pace_style, score_stakes, stakes_verdict, evaluate_axis_horse,
)


def make_entry(pop=8, distance=2000, frame=5, wc=57.0):
    return {'popularity': pop, 'distance': distance,
            'frame_number': frame, 'weight_carried': wc}


def make_prev(pop=5, pos=5, distance=2000, corner=None, headcount=16, wc=57.0):
    return {'popularity': pop, 'finish_position': pos, 'distance': distance,
            'corner_position': corner, 'headcount': headcount,
            'weight_carried': wc}


def names(signals):
    return {s['name'] for s in signals}


class TestPaceStyle(unittest.TestCase):
    def test_nige_senko_boundary(self):
        # 4/16 = 25% ちょうど → 逃先行
        self.assertEqual(_pace_style("3-3-4", 16), "逃先行")

    def test_chudan(self):
        # 5/16 = 31% → 中団
        self.assertEqual(_pace_style("5-5-5", 16), "中団")
        # 11/16 = 68.75% → 中団（70%以下）
        self.assertEqual(_pace_style("11", 16), "中団")

    def test_kohou(self):
        # 12/16 = 75% → 後方
        self.assertEqual(_pace_style("14-13-12", 16), "後方")

    def test_none_safety(self):
        self.assertIsNone(_pace_style(None, 16))
        self.assertIsNone(_pace_style("3-3", None))
        self.assertIsNone(_pace_style("3-3", 0))
        self.assertIsNone(_pace_style("", 16))
        self.assertIsNone(_pace_style("--", 16))


class TestPositiveSignals(unittest.TestCase):
    def test_s1_fires(self):
        _, sigs = score_stakes(make_entry(pop=9), make_prev(pop=2, pos=10))
        self.assertIn('S1_前走上位人気急落', names(sigs))

    def test_s1_pop_boundaries(self):
        # 8人気は対象外、12人気も対象外
        _, sigs = score_stakes(make_entry(pop=8), make_prev(pop=2, pos=10))
        self.assertNotIn('S1_前走上位人気急落', names(sigs))
        _, sigs = score_stakes(make_entry(pop=12), make_prev(pop=2, pos=10))
        self.assertNotIn('S1_前走上位人気急落', names(sigs))

    def test_s2_fires(self):
        _, sigs = score_stakes(make_entry(pop=13), make_prev(pop=5, pos=8))
        self.assertIn('S2_前走大敗穴', names(sigs))

    def test_s2_requires_7th_or_worse(self):
        _, sigs = score_stakes(make_entry(pop=13), make_prev(pop=5, pos=6))
        self.assertNotIn('S2_前走大敗穴', names(sigs))

    def test_s3_s5_both_fire(self):
        # 最強パターン: 前走4-6人気×1着 → 今回7-9人気 = S3+S5=6.5点
        total, sigs = score_stakes(make_entry(pop=8), make_prev(pop=5, pos=1))
        self.assertIn('S3_前走中人気好走', names(sigs))
        self.assertIn('S5_前走勝ち馬', names(sigs))
        self.assertEqual(total, 6.5)

    def test_s3_requires_win(self):
        # 前走2着はS3対象外（ROI 42円で除外済み）
        _, sigs = score_stakes(make_entry(pop=8), make_prev(pop=5, pos=2))
        self.assertNotIn('S3_前走中人気好走', names(sigs))

    def test_s4_excluded_by_s5(self):
        # 前走1着（S5発動）ならS4は加算しない
        _, sigs = score_stakes(make_entry(pop=8), make_prev(pop=8, pos=1),
                               prev2_pos=5)
        self.assertIn('S5_前走勝ち馬', names(sigs))
        self.assertNotIn('S4_上昇トレンド', names(sigs))

    def test_s4_fires_without_s5(self):
        _, sigs = score_stakes(make_entry(pop=8), make_prev(pop=8, pos=3),
                               prev2_pos=9)
        self.assertIn('S4_上昇トレンド', names(sigs))

    def test_s6_excluded_when_s3_s5_fired(self):
        # S3+S5発動時は距離延長でもS6を加算しない（三重複8.5点は未検証）
        total, sigs = score_stakes(
            make_entry(pop=8, distance=2200),
            make_prev(pop=5, pos=1, distance=2000))
        self.assertNotIn('S6_距離延長好走実績', names(sigs))
        self.assertEqual(total, 6.5)

    def test_s6_fires_with_s5_only(self):
        # S5単独（前走7人気1着）＋距離延長 → S6は発動する
        _, sigs = score_stakes(
            make_entry(pop=8, distance=2200),
            make_prev(pop=7, pos=1, distance=2000))
        self.assertIn('S5_前走勝ち馬', names(sigs))
        self.assertIn('S6_距離延長好走実績', names(sigs))

    def test_s7_outer_frame(self):
        # 逃先行×距離同等×4枠以上 → S7
        _, sigs = score_stakes(
            make_entry(pop=8, frame=6),
            make_prev(pos=4, corner="2-2-2", headcount=16))
        self.assertIn('S7_逃先行距離同等', names(sigs))

    def test_m4_inner_frame(self):
        # 逃先行×内枠1-3枠 → M4マイナス
        _, sigs = score_stakes(
            make_entry(pop=8, frame=2),
            make_prev(pos=4, corner="2-2-2", headcount=16))
        self.assertIn('M4_逃先行内枠', names(sigs))
        self.assertNotIn('S7_逃先行距離同等', names(sigs))

    def test_s8_fires(self):
        _, sigs = score_stakes(
            make_entry(pop=10),
            make_prev(pop=6, pos=10, corner="15-15-14", headcount=16))
        self.assertIn('S8_後方前走大敗', names(sigs))

    def test_s8_excluded_prev_favorite(self):
        # 前走1-3人気×後方大敗はS8対象外（S1+S8はROI 0円）
        _, sigs = score_stakes(
            make_entry(pop=10),
            make_prev(pop=2, pos=10, corner="15-15-14", headcount=16))
        self.assertNotIn('S8_後方前走大敗', names(sigs))

    def test_s9_weight_up(self):
        _, sigs = score_stakes(make_entry(pop=8, wc=58.0),
                               make_prev(pos=5, wc=56.0))
        self.assertIn('S9_斤量増加格上げ', names(sigs))

    def test_m5_weight_down(self):
        _, sigs = score_stakes(make_entry(pop=8, wc=55.0),
                               make_prev(pos=5, wc=57.0))
        self.assertIn('M5_斤量減少格下げ', names(sigs))

    def test_weight_missing_is_safe(self):
        entry = make_entry(pop=8)
        entry['weight_carried'] = None
        _, sigs = score_stakes(entry, make_prev(pos=5, wc=56.0))
        self.assertNotIn('S9_斤量増加格上げ', names(sigs))
        self.assertNotIn('M5_斤量減少格下げ', names(sigs))

    def test_d_jockey_is_reference_only(self):
        # D_騎手は表示されるがスコアに影響しない（score=0）
        total_with, sigs = score_stakes(make_entry(pop=8), make_prev(pos=5),
                                        jockey_win_rate=0.20)
        total_without, _ = score_stakes(make_entry(pop=8), make_prev(pos=5))
        self.assertIn('D_騎手勝率', names(sigs))
        self.assertEqual(total_with, total_without)


class TestM1Exclusion(unittest.TestCase):
    def test_m1_fires_plain(self):
        # 10人気以上×前走大敗、保護シグナルなし → M1
        _, sigs = score_stakes(make_entry(pop=12), make_prev(pop=8, pos=10))
        self.assertIn('M1_大穴前走大敗', names(sigs))

    def test_m1_excluded_by_s1(self):
        # S1発動馬（10-11人気×前走1-3人気）はM1除外
        _, sigs = score_stakes(make_entry(pop=10), make_prev(pop=2, pos=10))
        self.assertIn('S1_前走上位人気急落', names(sigs))
        self.assertNotIn('M1_大穴前走大敗', names(sigs))

    def test_m1_excluded_by_s2(self):
        _, sigs = score_stakes(make_entry(pop=12), make_prev(pop=5, pos=10))
        self.assertIn('S2_前走大敗穴', names(sigs))
        self.assertNotIn('M1_大穴前走大敗', names(sigs))

    def test_m1_excluded_by_s8(self):
        _, sigs = score_stakes(
            make_entry(pop=10),
            make_prev(pop=6, pos=10, corner="15-15-14", headcount=16))
        self.assertIn('S8_後方前走大敗', names(sigs))
        self.assertNotIn('M1_大穴前走大敗', names(sigs))

    def test_m1_fires_yasuda_kinen_case(self):
        # 安田記念のウォーターリヒト型: 後方×10人気×前走3人気13着
        # S1(9-11人気×前走1-3人気)は発動するがS8は発動しない
        # → S1が保護するのでM1は除外（S1発動馬のnetROIは高い）
        _, sigs = score_stakes(
            make_entry(pop=10),
            make_prev(pop=3, pos=13, corner="15-15-15", headcount=16))
        self.assertIn('S1_前走上位人気急落', names(sigs))
        self.assertNotIn('S8_後方前走大敗', names(sigs))
        self.assertNotIn('M1_大穴前走大敗', names(sigs))

    def test_m1_fires_pop12_prev_favorite(self):
        # 12人気以上×前走1-3人気×大敗: S1は発動しない（S1は9-11人気のみ）
        # 12-13人気×前走1-3人気はROI 0円（n=38）→ M1適用が正しい
        _, sigs = score_stakes(
            make_entry(pop=13),
            make_prev(pop=2, pos=12, corner="15-15-15", headcount=16))
        self.assertNotIn('S1_前走上位人気急落', names(sigs))
        self.assertIn('M1_大穴前走大敗', names(sigs))

    def test_m1_fires_kohou_prev_good_finish(self):
        # 旧バグの回帰テスト: 後方脚質でも前走好走(3着)ならS8は発動せず、
        # そもそもM1の外側条件(prev_pos>=7)も満たさないのでM1なし
        _, sigs = score_stakes(
            make_entry(pop=10),
            make_prev(pop=6, pos=3, corner="15-15-14", headcount=16))
        self.assertNotIn('S8_後方前走大敗', names(sigs))
        self.assertNotIn('M1_大穴前走大敗', names(sigs))


class TestEdgeCases(unittest.TestCase):
    def test_no_prev_returns_zero(self):
        total, sigs = score_stakes(make_entry(pop=8), None)
        self.assertEqual(total, 0.0)
        self.assertEqual(sigs, [])

    def test_mid_popularity_gap_no_signals(self):
        # 4-6人気帯は全シグナル対象外（検証済み空白帯）
        for pop in (4, 5, 6):
            total, sigs = score_stakes(
                make_entry(pop=pop),
                make_prev(pop=5, pos=1, corner="2-2-2", headcount=16),
                prev2_pos=9, jockey_win_rate=0.20)
            self.assertEqual(
                [s for s in sigs if s['score'] != 0], [],
                f"pop={pop} で加点/減点シグナルが発動: {names(sigs)}")

    def test_prev_pos_none_safe(self):
        # 前走中止(finish_position=NULL)でも落ちない
        total, sigs = score_stakes(make_entry(pop=10), make_prev(pop=5, pos=None))
        self.assertNotIn('M1_大穴前走大敗', names(sigs))

    def test_string_positions_safe(self):
        # DBから文字列で来ても落ちない（S4のfloat変換）
        prev = make_prev(pop=8, pos=3)
        total, sigs = score_stakes(make_entry(pop=8), prev, prev2_pos="10")
        self.assertIn('S4_上昇トレンド', names(sigs))


class TestVerdict(unittest.TestCase):
    def test_axis_verdicts(self):
        self.assertIn("軸候補", stakes_verdict(0, 1))
        self.assertIn("疑問", stakes_verdict(-1, 2))

    def test_hole_verdicts(self):
        self.assertIn("★★", stakes_verdict(5.0, 8))
        self.assertIn("★", stakes_verdict(3.0, 8))
        self.assertIn("△", stakes_verdict(1.0, 8))
        self.assertIn("消し", stakes_verdict(-2.0, 12))
        self.assertIn("スルー", stakes_verdict(0.5, 8))

    def test_axis_horse_eval(self):
        v, score = evaluate_axis_horse(make_entry(pop=1), make_prev(pop=2, pos=1))
        self.assertGreater(score, 0)
        v, score = evaluate_axis_horse(make_entry(pop=1), make_prev(pop=2, pos=10))
        self.assertLess(score, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
