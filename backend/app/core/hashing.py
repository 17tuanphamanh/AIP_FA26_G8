"""hash_action — băm Action để người duyệt phê duyệt đúng một ActionPlan (B15 chốt, B17 so lại).

JSON sắp khóa, UTF-8, SHA-256 (B11 mục 4): đổi thứ tự khóa không đổi hash [Chốt cổng 1].
Nhận Mapping hoặc Pydantic model vì core không được import domain.Action.
"""

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel


def hash_action(action: BaseModel | Mapping[str, Any]) -> str:
    data = action.model_dump(mode="json") if isinstance(action, BaseModel) else dict(action)
    canonical = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
