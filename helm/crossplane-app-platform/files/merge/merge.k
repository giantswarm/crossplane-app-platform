# Deep merge for Helm values: maps merge recursively, lists and scalars from `over` replace, null in `over` removes the key.
_is_map = lambda x -> bool { typeof(x) == "dict" }

merge_values = lambda base: {str:}, over: {str:} -> {str:} {
    _keys = [k for k in base if k not in over] + [k for k in over if over[k] != None]
    {
        k: (merge_values(base[k] if k in base and _is_map(base[k]) else {}, over[k]) if k in over and _is_map(over[k]) else (over[k] if k in over else base[k]))
        for k in _keys
    }
}
