"""Reciprocal Rank Fusion. No database."""

from __future__ import annotations

from alam.domain.rank_fusion import reciprocal_rank_fusion


class TestReciprocalRankFusion:
    def test_single_list_preserves_order(self) -> None:
        result = reciprocal_rank_fusion([["a", "b", "c"]])

        assert result == ["a", "b", "c"]

    def test_agreement_beats_a_single_top_rank(self) -> None:
        """ "a" is #1 on the vector branch only. "b" is #2 on the vector
        branch and #1 on the text branch. Appearing on both branches outweighs
        a single first-place finish — that is the entire reason to fuse two
        branches instead of picking the vector branch's ranking alone."""
        vector = ["a", "b"]
        text = ["b", "c"]

        result = reciprocal_rank_fusion([vector, text])

        assert result[0] == "b"

    def test_item_in_only_one_list_still_ranks(self) -> None:
        result = reciprocal_rank_fusion([["a"], ["b"]])

        assert set(result) == {"a", "b"}

    def test_empty_lists(self) -> None:
        assert reciprocal_rank_fusion([]) == []
        assert reciprocal_rank_fusion([[], []]) == []

    def test_no_duplicate_ids_in_output(self) -> None:
        result = reciprocal_rank_fusion([["a", "b"], ["a", "c"]])

        assert len(result) == len(set(result)) == 3

    def test_k_trades_off_a_single_top_rank_against_agreement(self) -> None:
        """ "x" is #1 on branch A only; "y" is #5 on both branches (behind
        distinct filler ids so the two branches don't also agree on those). A
        small k makes x's single top rank decisive; a large k flattens rank
        differences until y's presence on both branches wins instead — RRF's
        score contribution per list shrinks toward 1/k for every rank as k
        grows, so what matters at the limit is how many lists an id is in."""
        branch_a = ["x", "a1", "a2", "a3", "y"]
        branch_b = ["b1", "b2", "b3", "b4", "y"]

        tight = reciprocal_rank_fusion([branch_a, branch_b], k=0)
        loose = reciprocal_rank_fusion([branch_a, branch_b], k=1000)

        assert tight.index("x") < tight.index("y")
        assert loose.index("y") < loose.index("x")
