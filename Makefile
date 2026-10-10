# Android App Generator Makefile

# This Makefile provides a convenient way to automate the process using the `app_generator/build_app.py` script.

# ## Usage
#
# Run `make` with the following variables:
#
# - `START`: Starting app number (default: 1)
# - `END`: Ending app number (required)
# - `DIR`: Output directory (default: apps_output)
# - `INSTALL`: Set to `1` to include the `--install` flag
#
# ### Examples
#
# **1. Build apps 1 to 10 into `my_apps` folder:**
# ```bash
# make build END=10 DIR=my_apps
# ```
#
# **2. Build and install apps 1 to 5 into `test_install` folder:**
# ```bash
# make build END=5 DIR=test_install INSTALL=1
# ```
#
# **3. Build apps 1 to 600 (Mass Generation):**
# ```bash
# make build END=600
# ```
#
# **4. Clean up the output directory:**
# ```bash
# make clean DIR=my_apps
# ```
#
# ## Targets
#
# - `build`: Executes the build script.
# - `install`: Executes the build script with the `--install` flag.
# - `clean`: Removes the specified output directory.

PYTHON = python3
SCRIPT = app_generator/build_app.py
DIR ?= apps_output
START ?= 1
END ?= 1
INSTALL ?= 0

.PHONY: build install clean

build:
	$(PYTHON) $(SCRIPT) $(DIR) --start $(START) --end $(END) $(if $(filter 1,$(INSTALL)),--install,)

install:
	$(PYTHON) $(SCRIPT) $(DIR) --start $(START) --end $(END) --install

clean:
	rm -rf $(DIR)
