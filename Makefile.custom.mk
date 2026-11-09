.PHONY: validate-spike-case-b
validate-spike-case-b: ## Offline check of the Case B spike manifests (needs envsubst, kubeconform, flux-operator, yq).
	./spike/case-b/validate.sh

.PHONY: test-golden
test-golden: ## Golden render tests (needs bin/crossplane v2 CLI, helm, Docker for function-kcl).
	./tests/golden/run.sh

.PHONY: test-rbac
test-rbac: ## helm template assertions for the customer RBAC (needs helm, yq).
	./tests/rbac/run.sh

.PHONY: test-schedule
test-schedule: ## Checks the zero-window CEL rule text is in the XRD (needs helm, yq).
	./tests/schedule/run.sh
