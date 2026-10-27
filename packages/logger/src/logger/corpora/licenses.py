"""Verified licensing facts per dataset. Gates publication (decision 0004).

Verified 2026-08-15 against the primary sources cited on each entry. These are
kept in code, not only in prose, so that ``ingest_loghub(require_publishable=)``
can actually refuse a dataset instead of relying on someone remembering.

**The unresolved conflict, stated once:** loghub ships two licences that do not
agree. The repo ``LICENSE`` is a bespoke text -- "freely available for research
or academic work" plus a citation requirement -- which GitHub's detector cannot
match to any known licence (``spdx_id: NOASSERTION``). The Zenodo records that
actually host the data all declare ``cc-by-4.0``, which permits commercial use
and derivatives. No loghub statement says which one wins.

Consequence for this project: publishing a derived corpus as **research output**
is permitted under either reading, so every loghub-sourced dataset below is
marked ``PUBLISHABLE_WITH_ATTRIBUTION``. Commercial redistribution relies on the
CC BY reading alone and is *not* cleared by this module.
"""

from __future__ import annotations

from logger.corpora.base import DatasetLicense, DerivedDataPolicy

LOGHUB_REPO = "https://github.com/logpai/loghub"

LOGHUB_CITATION = (
    "Jieming Zhu, Shilin He, Pinjia He, Jinyang Liu, Michael R. Lyu. "
    "Loghub: A Large Collection of System Log Datasets for AI-driven Log "
    "Analytics. ISSRE 2023. arXiv:2008.06448"
)

_LOGHUB_CONFLICT = (
    "loghub repo LICENSE says 'research or academic work' (SPDX NOASSERTION); "
    "the Zenodo records hosting the data declare CC BY 4.0. Unresolved. "
    "Research/academic publication is permitted under both readings; "
    "commercial redistribution is not cleared."
)

HDFS = DatasetLicense(
    name="BSD (upstream) + loghub terms",
    url="http://people.iiis.tsinghua.edu.cn/~weixu/sospdata.html",
    derived_data=DerivedDataPolicy.PUBLISHABLE_WITH_ATTRIBUTION,
    attribution=(
        "Xu, Huang, Fox, Patterson, Jordan. Detecting Large-Scale System "
        f"Problems by Mining Console Logs. SOSP 2009. || {LOGHUB_CITATION}"
    ),
    notes=(
        "Cleanest of the six. Wei Xu's original page grants the data under a "
        "standard BSD licence and states it was produced by benchmark workload "
        "in a private cloud, so no privacy review is needed. Upstream-permissive "
        "independently of the loghub conflict."
    ),
)

BGL = DatasetLicense(
    name="Unstated (USENIX CFDR) + loghub terms",
    url="https://www.usenix.org/cfdr-data",
    derived_data=DerivedDataPolicy.PUBLISHABLE_WITH_ATTRIBUTION,
    attribution=(
        "Oliner, Stearley. What Supercomputers Say: A Study of Five System "
        f"Logs. DSN 2007. Data via USENIX CFDR (HPC4). || {LOGHUB_CITATION}"
    ),
    notes=(
        "WEAKEST LINK. The CFDR page carries no licence, no terms of use, and "
        "no research-only clause -- but also no affirmative grant of "
        "redistribution rights. Absence of a restriction is not a grant. "
        "Ungated public download, LLNL Blue Gene/L, cleared for public release; "
        "widely redistributed in the literature without objection. "
        "Logs are NOT sanitised -- review sampled rows for hostnames/usernames "
        f"before publishing. {_LOGHUB_CONFLICT}"
    ),
)

THUNDERBIRD = DatasetLicense(
    name="Unstated (USENIX CFDR) + loghub terms",
    url="https://www.usenix.org/cfdr-data",
    derived_data=DerivedDataPolicy.PUBLISHABLE_WITH_ATTRIBUTION,
    attribution=(
        "Oliner, Stearley. What Supercomputers Say: A Study of Five System "
        f"Logs. DSN 2007. Data via USENIX CFDR (HPC4). || {LOGHUB_CITATION}"
    ),
    notes=(
        "Same unstated-terms problem as BGL (Sandia National Labs). Logs are "
        "NOT sanitised and this is production syslog: usernames, hostnames and "
        "IPs appear in the message bodies. Privacy review required before "
        f"publishing derived rows. {_LOGHUB_CONFLICT}"
    ),
)

OPENSTACK = DatasetLicense(
    name="loghub terms (upstream DeepLog, no separate licence)",
    url=LOGHUB_REPO,
    derived_data=DerivedDataPolicy.PUBLISHABLE_WITH_ATTRIBUTION,
    attribution=(
        "Du, Li, Zheng, Srikumar. DeepLog: Anomaly Detection and Diagnosis "
        f"from System Logs through Deep Learning. CCS 2017. || {LOGHUB_CITATION}"
    ),
    notes=(
        "Not LogPAI-collected -- originates with the DeepLog authors (Utah), "
        "generated on CloudLab. No separate upstream licence located. "
        f"{_LOGHUB_CONFLICT}"
    ),
)

SPARK = DatasetLicense(
    name="loghub terms",
    url=LOGHUB_REPO,
    derived_data=DerivedDataPolicy.PUBLISHABLE_WITH_ATTRIBUTION,
    attribution=LOGHUB_CITATION,
    notes=(
        "LogPAI's own lab data (CUHK), provided as-is. Falls squarely under "
        f"loghub's own licence with no third-party layer. {_LOGHUB_CONFLICT}"
    ),
)

HADOOP = DatasetLicense(
    name="loghub terms (upstream ICSE'16, no separate licence)",
    url=LOGHUB_REPO,
    derived_data=DerivedDataPolicy.PUBLISHABLE_WITH_ATTRIBUTION,
    attribution=(
        "Lin, Zhang, Lou, Zhang, Chen. Log Clustering Based Problem "
        "Identification for Online Service Systems. ICSE 2016. || "
        f"{LOGHUB_CITATION}"
    ),
    notes=(
        "Lab cluster with injected failures; requires the ICSE'16 citation. "
        f"No separate upstream licence located. {_LOGHUB_CONFLICT}"
    ),
)

PUBLICATION_CHECKLIST = (
    "Ship the loghub LICENSE text verbatim ('shall be included in all copies').",
    f"Link {LOGHUB_REPO} for credit.",
    "Cite the loghub ISSRE'23 paper plus every per-dataset citation above.",
    "State prominently that the corpus is sampled, parsed and re-indexed -- "
    "CC BY requires indicating that changes were made.",
    "Acknowledge Jon Stearley and Adam Oliner for BGL/Thunderbird (CFDR custom).",
    "Retain the BSD notice for HDFS.",
    "Privacy-review sampled rows from BGL/Thunderbird/OpenStack/Hadoop: loghub "
    "states the logs are NOT sanitised or anonymised.",
)
