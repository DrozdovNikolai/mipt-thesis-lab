from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from h2.cloudru_billing import BillingUnavailable, consumption


def test_billing_paginates_and_omits_deleted_entries():
    client = SimpleNamespace(request=Mock(side_effect=[
        {"consumptions": [{"amount_nds": 2}] * 100},
        {"consumptions": [{"amount_nds": 3}, {"amount_nds": 999, "is_delete": True}]}]))
    query = {"project_ids": "p", "end_date": "frozen-end"}
    snapshot = consumption(client, query)
    assert snapshot["preliminary_rub"] == 203
    assert len(snapshot["consumptions"]) == 102
    assert [call.args[2]["page_filter.page"] for call in client.request.call_args_list] == [1, 2]
    assert query == {"project_ids": "p", "end_date": "frozen-end"}


@pytest.mark.parametrize("response", [{}, {"consumptions": None},
    {"consumptions": [{}]}, {"consumptions": [{"amount_nds": "nan"}]}])
def test_malformed_billing_is_not_reported_as_zero(response):
    client = SimpleNamespace(request=Mock(return_value=response))
    with pytest.raises(BillingUnavailable):
        consumption(client, {})


def test_pagination_is_bounded_and_never_returns_a_partial_sum():
    client = SimpleNamespace(request=Mock(return_value={"consumptions": [{"amount_nds": 1}] * 100}))
    with pytest.raises(BillingUnavailable, match="incomplete"):
        consumption(client, {})
    assert client.request.call_count == 20
