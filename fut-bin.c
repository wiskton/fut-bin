#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <sys/prctl.h>
#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>

#define SCRIPT_TARGET "/home/willem/Documents/GitHub/fut-bin/tray.py"

int main(int argc, char *argv[]) {
    prctl(PR_SET_NAME, "fut-bin", 0, 0, 0);

    PyConfig config;
    PyConfig_InitPythonConfig(&config);
    config.parse_argv = 0;

    PyConfig_SetString(&config, &config.program_name, L"fut-bin");
    wchar_t *w_exe = Py_DecodeLocale("/home/willem/.local/bin/fut-bin", NULL);
    if (w_exe) {
        PyConfig_SetString(&config, &config.executable, w_exe);
        PyMem_RawFree(w_exe);
    }

    PyStatus status = PyConfig_SetBytesArgv(&config, argc, argv);
    if (PyStatus_Exception(status)) {
        PyConfig_Clear(&config);
        return 1;
    }

    status = Py_InitializeFromConfig(&config);
    if (PyStatus_Exception(status)) {
        PyConfig_Clear(&config);
        return 1;
    }
    PyConfig_Clear(&config);

    FILE *fp = fopen(SCRIPT_TARGET, "r");
    if (!fp) {
        fprintf(stderr, "Erro ao abrir %s\n", SCRIPT_TARGET);
        return 1;
    }

    int ret = PyRun_SimpleFile(fp, SCRIPT_TARGET);
    fclose(fp);

    fflush(stdout);
    fflush(stderr);
    Py_Finalize();
    return ret;
}
