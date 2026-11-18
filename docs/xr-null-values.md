# Does a `null` in `values` survive the namespaced XR CRD?

Yes, for `spec.values` and `spec.targets.static[].values`, as long as the XRD declares them as
`type: object` with `x-kubernetes-preserve-unknown-fields: true` and no `properties` (as `xrd.yaml` does).
Checked from source; no cluster was touched. Versions: Crossplane v2.4.3, crossplane-runtime v2.4.3,
k8s.io/apiextensions-apiserver v0.35.0 (`go.mod:22` of crossplane v2.4.3).

1. Crossplane copies the XRD schema into the XR CRD as is: `parseSchema` unmarshals `openAPIV3Schema` into
   `extv1.JSONSchemaProps` (crossplane-runtime `pkg/xcrd/crd.go:252-262`) and `spec.properties` are copied whole
   (`crd.go:206`, `maps.Copy(cSpec.Properties, xSpec.Properties)`). `XPreserveUnknownFields` on the property travels with it.
   Nothing in Crossplane adds `nullable` or strips fields.
2. The API server prunes non-nullable nulls before defaulting: `PruneNonNullableNullsWithoutDefaults`
   (apiextensions-apiserver `pkg/apiserver/schema/defaulting/prunenulls.go:44-66`) deletes a key only when
   `isNonNullableNonDefaultableNull` (`prunenulls.go:21-23`) holds, which needs `s != nil`, the schema of that field.
   For a key under `values` there is no schema: `getSchemaForField` (`prunenulls.go:25-37`) returns `nil` when the parent
   has neither `Properties[field]` nor `AdditionalProperties`. So the null is kept. Had `values` declared
   `properties`, a null for a declared key would be pruned.
3. Unknown-field pruning does not touch it: `prune` returns early for `XPreserveUnknownFields`
   (apiextensions-apiserver `pkg/apiserver/schema/pruning/algorithm.go:57-60`).
4. Crossplane hands the XR to the function as an unstructured object encoded with `structpb.NewStruct`
   (`internal/xfn/utils.go:54-57`, called at `internal/controller/apiextensions/composite/composition_functions.go:923`),
   whose null is `NullValue` (protobuf-go behavior, not re-read here).
5. Only a top-level `values: null` (the field itself, which has a schema) is pruned; that is harmless.

Runtime evidence for the function side: `tests/golden/values-layers` has a per-target `drop: null` that removes a global
key through `crossplane composition render` + function-kcl. Not verified: a live API server round trip (PoC on a cluster).
