SERIES ?= xenial

clean:
	rm -rf trusty xenial

build: clean
	charm build -s $(SERIES)

.PHONY: clean
