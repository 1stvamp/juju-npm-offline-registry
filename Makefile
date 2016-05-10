SERIES ?= xenial

build:
	charm build -s $(SERIES)

deploy: build
	juju deploy local:$(SERIES)/npm-offline-registry

upgrade: build
	juju upgrade-charm npm-offline-registry

.PHONY: build deploy upgrade
