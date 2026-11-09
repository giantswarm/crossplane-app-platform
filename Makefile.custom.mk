.PHONY: validate-spike-case-b
validate-spike-case-b: ## Offline check of the Case B spike manifests (needs envsubst, kubeconform, flux-operator, yq).
	./spike/case-b/validate.sh
