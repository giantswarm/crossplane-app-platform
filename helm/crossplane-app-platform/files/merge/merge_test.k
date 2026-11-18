import .merge

test_map_merge = lambda {
    r = merge.merge_values({a = {x = 1, y = 2}, b = 1}, {a = {y = 3, z = 4}})
    assert r == {a = {x = 1, y = 3, z = 4}, b = 1}
}
test_list_replace = lambda {
    assert merge.merge_values({l = [1, 2, 3]}, {l = [9]}) == {l = [9]}
}
test_scalar_override = lambda {
    assert merge.merge_values({s = "a", n = 1}, {s = "b", n = 2}) == {s = "b", n = 2}
}
test_null_deletes = lambda {
    assert merge.merge_values({a = 1, b = 2}, {a = None}) == {b = 2}
}
test_null_deletes_nested = lambda {
    assert merge.merge_values({a = {x = 1, y = 2}}, {a = {x = None}}) == {a = {y = 2}}
}
test_null_on_missing_key_is_noop = lambda {
    assert merge.merge_values({a = 1}, {zz = None}) == {a = 1}
}
test_type_change_replaces = lambda {
    assert merge.merge_values({a = {x = 1}}, {a = "s"}) == {a = "s"}
    assert merge.merge_values({a = "s"}, {a = {x = 1}}) == {a = {x = 1}}
}
test_empty_base = lambda {
    assert merge.merge_values({}, {a = {b = 1}, c = None}) == {a = {b = 1}}
}
test_null_nested_in_new_map = lambda {
    assert merge.merge_values({}, {a = {b = None, c = 1}}) == {a = {c = 1}}
}
