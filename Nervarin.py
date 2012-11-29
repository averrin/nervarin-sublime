import sublime
import sublime_plugin
import os
import subprocess
import threading
import functools
import urllib2
import json

w = sublime.active_window()
project_path = w.folders()[0]
settings_path = os.path.join(project_path, "project.json")

sync = False
if os.path.isfile(settings_path):
    print 'Read project settings'
    with file(settings_path, 'r') as f:
        settings = json.load(f)
    sync = True
else:
    print 'No "project.json" in %s' % project_path


if sync:
    projects_url = '%(en_server)s/collectionapi/PROJECTS' % settings
    err = False
    try:
        request = urllib2.Request(projects_url)
        request.add_header('X-Auth-Token', settings['token'])
        http_file = urllib2.urlopen(request, timeout=15)
        projects = json.load(http_file)

    except (urllib2.HTTPError) as (e):
        err = '%s: HTTP error %s contacting API' % (__name__, str(e.code))
    except (urllib2.URLError) as (e):
        err = '%s: URL error %s contacting API' % (__name__, str(e.reason))

    if err:
        print '!!', err
    else:
        project_json = {}
        for p in projects:
            if p['title'] == settings['project']:
                project_json = p
                break
        if project_json:
            print 'Project loaded'
            sp = subprocess.Popen(['ssh-pageant'], shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            _env = sp.communicate()
            sync_sh = os.path.abspath(os.path.expanduser('~/.%s.sync.sh' % settings['project']))
            with file(sync_sh, 'w') as f:
                f.write(_env[0] + '\n' + 'rsync -avzu --del $(cygpath "$1") $2;')
            sync_sh = "~/.%s.sync.sh" % settings['project']
            update_sh = os.path.abspath(os.path.expanduser('~/.%s.update.sh' % settings['project']))
            cmd = _env[0].replace('\r', '')
            cmd += '\n'
            cmd += 'rsync -avzu --del '
            for ep in settings['exclude']:
                cmd += '--exclude=%s ' % ep
            cmd += ' $1 $(cygpath "$2");'
            with file(update_sh, 'w') as f:
                f.write(cmd)
            update_sh = "~/.%s.update.sh" % settings['project']


def main_thread(callback, *args, **kwargs):
    # sublime.set_timeout gets used to send things onto the main thread
    # most sublime.[something] calls need to be on the main thread
    sublime.set_timeout(functools.partial(callback, *args, **kwargs), 0)


def do_when(conditional, callback, *args, **kwargs):
    if conditional():
        return callback(*args, **kwargs)
    sublime.set_timeout(functools.partial(do_when, conditional, callback, *args, **kwargs), 50)


def _make_text_safeish(text, fallback_encoding, method='decode'):
    # The unicode decode here is because sublime converts to unicode inside
    # insert in such a way that unknown characters will cause errors, which is
    # distinctly non-ideal...
    try:
        unitext = getattr(text, method)('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        unitext = getattr(text, method)(fallback_encoding)
    return unitext


class CommandThread(threading.Thread):
    def __init__(self, command, on_done, working_dir="", fallback_encoding="", **kwargs):
        threading.Thread.__init__(self)
        self.command = command
        self.on_done = on_done
        self.working_dir = working_dir
        if "stdin" in kwargs:
            self.stdin = kwargs["stdin"]
        else:
            self.stdin = None
        if "stdout" in kwargs:
            self.stdout = kwargs["stdout"]
        else:
            self.stdout = subprocess.PIPE
        self.fallback_encoding = fallback_encoding
        self.kwargs = kwargs

    def run(self):
        try:
            # Per http://bugs.python.org/issue8557 shell=True is required to
            # get $PATH on Windows. Yay portable code.
            shell = os.name == 'nt'
            if self.working_dir != "":
                os.chdir(self.working_dir)

            proc = subprocess.Popen(self.command,
                stdout=self.stdout, stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
                shell=shell, universal_newlines=True)
            output = proc.communicate(self.stdin)[0]
            if not output:
                output = ''
            # if sublime's python gets bumped to 2.7 we can just do:
            # output = subprocess.check_output(self.command)
            main_thread(self.on_done, _make_text_safeish(output, self.fallback_encoding), **self.kwargs)
        except subprocess.CalledProcessError, e:
            main_thread(self.on_done, e.returncode)
        except OSError, e:
            if e.errno == 2:
                main_thread(sublime.error_message, "binary could not be found in PATH\n\nPATH is: %s" % os.environ['PATH'])
            else:
                raise e


def run_command(command, callback=None, show_status=True,
        filter_empty_args=True, no_save=False, **kwargs):
    if filter_empty_args:
        command = [arg for arg in command if arg]
    if 'working_dir' not in kwargs:
        kwargs['working_dir'] = project_path

    if not callback:
        callback = lambda x: sublime.status_message('=Done=')

    thread = CommandThread(command, callback, **kwargs)
    thread.start()

    if show_status:
        message = kwargs.get('status_message', False) or ' '.join(command)
        sublime.status_message(message)


def sync_local(path, remote):
    folder, file_name = os.path.split(path)
    cygwin_path = path.replace('C:\\', '/cygdrive/c/').replace('\\', '/')
    if folder.startswith(project_path):
        file_path = folder.replace(project_path, '').replace('\\', '/') + '/' + file_name
        if file_path.startswith('\\'):
            file_path = file_path[1:]
        print 'do rsync %s' % file_path
        sync = ["""bash %s %s %s""" % (sync_sh, cygwin_path, remote + '/' + file_path)]
        print sync
        callback = lambda x: sublime.status_message('=%s synced=' % settings['project'])
        run_command(sync, callback)


def update_project(path, local):
    cygwin_path = local.replace('C:\\', '/cygdrive/c/').replace('\\', '/')
    print 'do update from %s' % path
    sync = ["""bash %s %s %s""" % (update_sh, path, cygwin_path)]
    print sync
    callback = lambda x: sublime.status_message('=%s updated=' % settings['project'])
    run_command(sync, callback)


class RsyncOnSave(sublime_plugin.EventListener):
    def on_post_save(self, view):
        sync_local(view.file_name(), project_json['sync_url'])


class UpdateProjectCommand(sublime_plugin.WindowCommand):

    def run(self):
        if project_json:
            parent = os.path.split(project_path)[0]
            update_project(project_json['sync_url'], parent)
        else:
            sublime.status_message('=Unknown project=')
