# Android test-app generator. See README.md for details.
#
#   make build END=500 [START=1] [DIR=apps_output] [INSTALL=1] [LAUNCH=1] [WORKERS=8]
#              [LEGACY_ICONS=1]
#   make install END=5             build and install normal apps 1..5
#   make changing END=20 LAUNCH=1  icon-switching apps; also FRAMES=6 INTERVAL=60
#                                  PHASE=sync|stagger LABEL_MODE=same|frame WAKEUP=1 WHITELIST=1
#   make signal ACTION=switch INDEX=2   control installed switchers (switch|auto|stop|reset|status)
#   make uninstall [KIND=all]      remove generated apps from the device (normal|changing|all)
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
LEGACY_ICONS ?= 0
FRAMES ?= 6
INTERVAL ?= 60
PHASE ?= sync
LABEL_MODE ?= same
WAKEUP ?= 0
WHITELIST ?= 0
ACTION ?= status
INDEX ?=
KIND ?= all
CONFIG ?=

flag = $(if $(filter 1,$(1)),$(2))
CONFIG_OPT = $(if $(CONFIG),--config '$(CONFIG)')
COMMON = '$(DIR)' --start $(START) --end $(END) $(call flag,$(INSTALL),--install) \
	$(call flag,$(LAUNCH),--launch) $(if $(WORKERS),--workers $(WORKERS)) $(CONFIG_OPT)

NORMAL_OPTS = $(call flag,$(LEGACY_ICONS),--legacy-icons)
CHANGING_OPTS = --frames $(FRAMES) --interval $(INTERVAL) --phase $(PHASE) --label-mode $(LABEL_MODE) \
	$(call flag,$(WAKEUP),--wakeup) $(call flag,$(WHITELIST),--whitelist)

.PHONY: build install changing signal uninstall doctor test clean

build:
	$(APKGEN) normal $(COMMON) $(NORMAL_OPTS)

install:
	$(APKGEN) normal $(COMMON) $(NORMAL_OPTS) --install

changing:
	$(APKGEN) changing $(COMMON) $(CHANGING_OPTS)

signal:
	$(APKGEN) signal $(ACTION) $(if $(INDEX),--index $(INDEX)) $(CONFIG_OPT)

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
