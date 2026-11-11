# Do CEL `x-kubernetes-validations` on the XRD reach the XR CRD?

Yes. Checked against crossplane-runtime v2.4.3 (the version Crossplane v2.4.3 uses, go.mod:12),
`pkg/xcrd/crd.go`, called from `internal/controller/apiextensions/definition/reconciler.go:270`
(`xcrd.ForCompositeResource`) in crossplane/crossplane v2.4.3:

- `parseSchema` unmarshals the XRD `openAPIV3Schema` into `extv1.JSONSchemaProps`, which has `XValidations` (crd.go:252-262).
- Root rules are copied: `crdv.Schema.OpenAPIV3Schema.XValidations = s.XValidations` (crd.go:184).
- `spec` rules are appended: `cSpec.XValidations = append(cSpec.XValidations, xSpec.XValidations...)` (crd.go:202).
- `status` rules are copied (crd.go:213).
- Rules on nested fields (for example `spec.chart`) travel with the property: `maps.Copy(cSpec.Properties, xSpec.Properties)` copies whole `JSONSchemaProps` values (crd.go:206).

Not verified: that a live API server rejects an object (no cluster was touched). `crossplane composition render`
does not validate against the XRD. The XRD has one nested rule on `spec.chart` for the PoC to confirm on a cluster.
