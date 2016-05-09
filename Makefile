SERIES ?= xenial

clean:
	rm -rf trusty xenial

build:
	charm build -s $(SERIES)

.PHONY: clean
