# Android test-app generator. See README.md for details.
#
#   make build END=500 [START=1] [DIR=apps_output] [INSTALL=1] [LAUNCH=1] [WORKERS=8]
#   make install END=5             build and install apps 1..5
#   make uninstall [KIND=all]      remove generated apps from the device (normal|all)
#   make doctor                    show and check the resolved toolchain
#   make test                      run the unit tests
#   make clean DIR=my_apps         delete an output directory (default DIR is apps_output!)
#
# CONFIG=path selects a toolchain config file (default: config.local.toml).

PYTHON ?= python3
APKGEN = $(PYTHON) -m apkgen
DIR ?= apps_output
START ?= 1
END ?= 1
INSTALL ?= 0
LAUNCH ?= 0
WORKERS ?=
KIND ?= all
CONFIG ?=

flag = $(if $(filter 1,$(1)),$(2))
CONFIG_OPT = $(if $(CONFIG),--config '$(CONFIG)')
COMMON = '$(DIR)' --start $(START) --end $(END) $(call flag,$(INSTALL),--install) \
	$(call flag,$(LAUNCH),--launch) $(if $(WORKERS),--workers $(WORKERS)) $(CONFIG_OPT)

.PHONY: build install uninstall doctor test clean

build:
	$(APKGEN) normal $(COMMON)

install:
	$(APKGEN) normal $(COMMON) --install

uninstall:
	$(APKGEN) uninstall --kind $(KIND) $(CONFIG_OPT)

doctor:
	$(APKGEN) doctor $(CONFIG_OPT)

test:
	$(PYTHON) -m unittest discover -s tests -t . -v

# Refuses the repository, $HOME, any directory containing either of them, and any directory
# with a .git inside.
clean:
	@d=$$(realpath -m -- '$(DIR)') && [ -n "$$d" ] || { echo "refusing: cannot resolve DIR='$(DIR)'"; exit 1; }; \
	for p in "$$(realpath .)" "$$(realpath -m -- "$$HOME")"; do \
		case "$$p/" in "$${d%/}/"*) echo "refusing to delete '$(DIR)': it is or contains $$p"; exit 1;; esac; \
	done
	@if [ -e '$(DIR)/.git' ]; then echo "refusing to delete '$(DIR)': it contains .git"; exit 1; fi
	rm -rf -- '$(DIR)'
