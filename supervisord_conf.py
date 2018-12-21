import os

cwd = os.getcwd()

config = """
; ==================================
;  google form  supervisor
; ==================================

; the name of your supervisord program
[program:gform]

; Set full path to news producer  program if using virtualenv
command={}/.venv/bin/python gform.spam


; The directory to my project
directory={}

; If supervisord is run as the root user, switch users to this UNIX user account
; before doing any processing.
user=user

; Supervisor will start as many instances of this program as named by numprocs
numprocs=1


; If true, this program will start automatically when supervisord is started
autostart=true

; May be one of false, unexpected, or true. If false, the process will never
; be autorestarted. If unexpected, the process will be restart when the program
; exits with an exit code that is not one of the exit codes associated with this
; process’ configuration (see exitcodes). If true, the process will be
; unconditionally restarted when it exits, without regard to its exit code.
autorestart=true

; The total number of seconds which the program needs to stay running after
; a startup to consider the start successful.
startsecs=3

; Need to wait for currently executing tasks to finish at shutdown.
; Increase this if you have very long running tasks.
stopwaitsecs = 2

; When resorting to send SIGKILL to the program to terminate it
; send SIGKILL to its whole process group instead,
; taking care of its children as well.
killasgroup=true

; if your broker is supervised, set its priority higher
; so it starts first
priority=998
""".format(cwd, cwd)

with open("gform.conf", "w") as fp:
    fp.write(config)

print("created config file  gform.conf to current directory")
