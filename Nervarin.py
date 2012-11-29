import sublime
import sublime_plugin
import os
from subprocess import *
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
            sp = Popen(['ssh-pageant'], shell=True, stdout=PIPE, stderr=PIPE)
            _env = sp.communicate()
            sync_sh = os.path.abspath(os.path.expanduser('~/sync.sh'))
            with file(sync_sh, 'w') as f:
                f.write(_env[0] + '\n' + 'rsync -avzu --del $(cygpath "$1") $2;')
            sync_sh = "~/sync.sh"
            update_sh = os.path.abspath(os.path.expanduser('~/update.sh'))
            cmd = _env[0].replace('\r', '')
            cmd += '\n'
            cmd += 'rsync -avzu --del '
            for ep in settings['exclude']:
                cmd += '--exclude=%s ' % ep
            cmd += ' $1 $(cygpath "$2");'
            with file(update_sh, 'w') as f:
                f.write(cmd)
            update_sh = "~/update.sh"


def sync_local(path, remote):
    folder, file_name = os.path.split(path)
    cygwin_path = path.replace('C:\\', '/cygdrive/c/').replace('\\', '/')
    if folder.startswith(project_path):
        file_path = folder.replace(project_path, '').replace('\\', '/') + '/' + file_name
        if file_path.startswith('\\'):
            file_path = file_path[1:]
        print "=" * 8
        print 'do rsync %s' % file_path
        sync = ["""bash %s %s %s""" % (sync_sh, cygwin_path, remote + '/' + file_path)]
        print sync
        p = Popen(sync, shell=True, stdout=PIPE, stderr=PIPE)
        sublime.set_timeout(lambda: get_result(p), 1000)


def update_project(path, local):
    cygwin_path = local.replace('C:\\', '/cygdrive/c/').replace('\\', '/')
    print "=" * 8
    print 'do update from %s' % path
    sync = ["""bash %s %s %s""" % (update_sh, path, cygwin_path)]
    print sync
    p = Popen(sync, shell=True, stdout=PIPE, stderr=PIPE)
    sublime.set_timeout(lambda: get_result(p), 1000)


def get_result(p):
    r = p.communicate()
    if r[0].strip():
        sublime.status_message('=%s synced=' % settings['project'])
    else:
        print r
        print r[1]
        sublime.status_message('=%s NOT synced=' % settings['project'])
    print "=" * 8


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
