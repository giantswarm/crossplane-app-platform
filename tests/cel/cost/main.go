// Runs the kube-apiserver CRD validation on the schema of an XRD. It includes the CEL cost
// estimator, which `crossplane resource validate` does not run: a rule over the budget makes
// Crossplane fail to create the CRD on a real cluster.
package main

import (
	"context"
	"fmt"
	"os"
	"strings"

	apiext "k8s.io/apiextensions-apiserver/pkg/apis/apiextensions"
	v1 "k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/v1"
	"k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/validation"
	"k8s.io/apimachinery/pkg/runtime"
	"sigs.k8s.io/yaml"
)

type xrd struct {
	Metadata struct{ Name string }
	Spec     struct {
		Group    string
		Names    v1.CustomResourceDefinitionNames
		Versions []struct {
			Name   string
			Schema v1.CustomResourceValidation
		}
	}
}

func main() {
	b, err := os.ReadFile(os.Args[1])
	if err != nil {
		panic(err)
	}
	var x xrd
	if err := yaml.Unmarshal(b, &x); err != nil {
		panic(err)
	}
	names := x.Spec.Names
	if names.Singular == "" {
		names.Singular = strings.ToLower(names.Kind)
	}
	if names.ListKind == "" {
		names.ListKind = names.Kind + "List"
	}
	crd := v1.CustomResourceDefinition{Spec: v1.CustomResourceDefinitionSpec{
		Group: x.Spec.Group, Names: names, Scope: v1.NamespaceScoped,
	}}
	crd.Name = x.Metadata.Name
	for i, v := range x.Spec.Versions {
		s := v.Schema
		crd.Spec.Versions = append(crd.Spec.Versions, v1.CustomResourceDefinitionVersion{
			Name: v.Name, Served: true, Storage: i == 0, Schema: &s,
		})
	}
	crd.Status.StoredVersions = []string{x.Spec.Versions[0].Name}

	sc := runtime.NewScheme()
	_ = v1.AddToScheme(sc)
	_ = apiext.AddToScheme(sc)
	var in apiext.CustomResourceDefinition
	if err := sc.Convert(&crd, &in, nil); err != nil {
		panic(err)
	}
	errs := validation.ValidateCustomResourceDefinition(context.Background(), &in)
	for _, e := range errs {
		fmt.Println(e.Error())
	}
	if len(errs) > 0 {
		os.Exit(1)
	}
	fmt.Println("PASS CRD schema and CEL cost")
}
