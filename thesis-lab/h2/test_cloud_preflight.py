from h2.cloud_preflight import assess_quotas, quota_requirements


def observations(rows):
    return {"quota_all": {"quota_limits": [{"quota_id": key, "limit": value, "usage": 0}
                                           for key, value in rows.items()]}}


def test_legacy_global_quota_account_remains_supported():
    assert all(x["fits"] for x in assess_quotas(observations(quota_requirements())))


def test_zonal_account_does_not_use_zero_legacy_placeholders():
    rows = quota_requirements(zonal=True)
    rows.update({"compute.instanceCores.count": 0, "compute.instanceMemory.size": 0,
                 "compute.ssdDisks.size": 0})
    checks = assess_quotas(observations(rows))
    assert all(x["fits"] for x in checks)
    assert any(x["id"] == "compute.instanceCores.count.ru-central1-a" for x in checks)


def test_insufficient_quota_in_target_zone_is_not_filled_from_another_zone():
    rows = quota_requirements(zonal=True)
    rows["compute.instanceCores.count.ru-central1-a"] = 2
    rows["compute.instanceCores.count.ru-central1-d"] = 32
    checks = assess_quotas(observations(rows))
    failed = [x for x in checks if not x["fits"]]
    assert len(failed) == 1
    assert failed[0]["id"] == "compute.instanceCores.count.ru-central1-a"
    assert failed[0]["available"] == 2
