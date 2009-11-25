#!/usr/bin/python
#######################################################################
#    Copyright (C) 2009 Bryan Bishop <kanzure@gmail.com>
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#######################################################################

"""
web.py - a tiny web server front end to skdb :)

you probably want:
    python run_web.py

to execute unit tests and diagnostics:
    python web.py
"""

#######################################################################
#                           header
#                   module importing, setup, etc.
#continued near end of file
#######################################################################

#save a few headaches..
if __name__ == "__main__":
    #another check for __main__ is in this file too
    print "are you sure you don't want:\n\tpython run_web.py\n\n"

import os
import sys
#sys.stdout = sys.stderr

from copy import copy
from string import join

bryan_message = "bryan hasn't got this far yet"
user_dir = "users/"
templates_dir = "templates/"
#this doesn't work like i want it to yet
def template_check():
    '''checks if templates need to be recompiled
    recompiles them if necessary
    
    situations:
        (1) .tmpl files exist and no corresponding .py file
        (2) .tmpl file has been updated and .py file needs to be recompiled'''
    #TODO: implement situation (2)
    os.system("cd " + templates_dir + "; cheetah compile *.tmpl")
    return

    #compile new templates
    to_recompile = []
    files = os.listdir(templates_dir)
    for file in files:
        if len(file)>5:
            if file[-5:] == ".tmpl":
                if not os.path.exists(os.path.join(templates_dir, file[:-5] + ".py")): to_recompile.append(file)

    to_compile = join(to_recompile, " ")
    if len(to_recompile) > 0: os.system("cd templates; cheetah compile " + to_compile)

#compile the templates if necessary
template_check()

#cherrypy
import cherrypy
from cherrypy.test import helper, webtest
_cperror = cherrypy._cperror

cherrypy.config.update({
    'server.socket_port': 8081,
    'server.socket_host': "0.0.0.0",
    'server.log_to_screen': True,
    'environment': "embedded",
    #url: http://www.ibm.com/developerworks/xml/library/os-cherrypy/
    #the following lines may be deprecated (from cp2)
    #'server.sessionStorageType': "ram",
    #'server.sessionCookieName': "skdb_session_cookie",
    })

#cheetah templates
#         __  ____________  __
#         \ \/            \/ /
#          \/    *   *     \/
#           \      |       / 
#            \  ==----==  / 
#             \__________/
#
from Cheetah.Template import Template
from templates import PackageIndex, IndexTemplate, PackageView

import urllib
import yaml
import unittest
from md5 import md5

import getpass
if getpass.getuser() == "www-data":
    #this is just for the PYTHONPATH environmental variable
    #on apache, web.py runs as www-data and needs this extra information
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), os.path.pardir))
    sys.path.insert(0, os.path.dirname(__file__))
    sys.stdout = sys.stderr

import dulwich
from dulwich.repo import Repo
from dulwich.objects import parse_timezone, Blob, Commit, Tree

import skdb

def add_newlines(output):
    return output.replace("\n", "\n<br />")

def handle_error():
    '''makes '500 internal server error' not suck'''
    cherrypy.response.status = 500
    cherrypy.response.body = add_newlines(_cperror.format_exc())

#######################################################################
#            user authentication stuff, demo, etc.
#######################################################################
#url: http://tools.cherrypy.org/wiki/AuthenticationAndAccessRestrictions
SESSION_KEY = "_cp_user"

def load_top_level_domain_names():
    '''run ./update_valid_tlds.sh to get the latest list from IANA'''
    tld_fh = open("valid_top_level_domains", "r")
    temp_tlds = tld_fh.read()
    tld_fh.close()
    temp_tlds2 = temp_tlds.split("\n")
    TLDs = []
    for tld in temp_tlds2:
        TLDs.append(tld.lower())
    TLDs.remove("") #cleanup
    return TLDs

#load up top level domain name list
TLDs = load_top_level_domain_names()

#url: http://commandline.org.uk/python/email-syntax-check/
def invalid_email(email_address, domains=TLDs):
    '''checks for syntactically invalid email address'''
    
    #email address must be at least 7 characters in total
    if len(email_address) < 7: return True #address too short

    #split up email address into parts
    try:
        local_part, domain_name = email_address.rsplit('@', 1)
        host, top_level = domain_name.rsplit('.', 1)
        top_level = top_level.lower()
    except ValueError: return True #address does not have enough parts
    
    #check for country code or generic TLD
    if len(top_level) != 2 and top_level not in domains: return True #not a TLD

    for i in '-_.%+.':
        local_part = local_part.replace(i, "")
    for i in '-_.':
        host = host.replace(i, "")

    if local_part.isalnum() and host.isalnum(): return False #email address is fine
    else: return True #email address has funny characters

def is_valid_email(email_address):
    '''see invalid_email please'''
    return not invalid_email(email_address)

def is_valid_user(username, password):
    '''verifies credentials
    returns True or False'''
    filepath = os.path.join(user_dir, username + ".yaml")

    #check that the right file exists (for the user)
    if not os.path.exists(filepath): return False

    user = yaml.load(open(filepath, "r"))
    if md5(password).hexdigest() == user.password: return True
    return False
check_credentials = is_valid_user

def check_user_exists(username):
    filepath = os.path.join(user_dir, username + ".yaml")
    return os.path.exists(filepath)

def check_auth(*args, **kwargs):
    '''a tool that looks in config for 'auth.require'. if found and it
    is not None, a login is required and the entry is evaluated as alist of
    conditions that the user must fulfill'''
    conditions = cherrypy.request.config.get('auth.require', None)
    #format GET params
    get_parmas = urllib.quote(cherrypy.request.request_line.split()[1])
    if conditions is not None:
        user = cherrypy.session.get(SESSION_KEY)
        if user:
            cherrypy.request.login = user.username
            for condition in conditions:
                #a condition is just a callable that returns true or false
                if not condition():
                    #send old page as from_page parameter
                    raise cherrypy.HTTPRedirect("/auth/login?from_page=%s" % get_parmas)
        else:
            #send old page as from_page parameter
            raise cherrypy.HTTPRedirect("/auth/login?from_page=%s" % get_parmas)

def require(*conditions):
    '''a decorator that appends conditions to the auth.require config variable'''
    def decorate(f):
        if not hasattr(f, '_cp_config'):
            f._cp_config = dict()
        if 'auth.require' not in f._cp_config:
            f._cp_config['auth.require'] = []
        f._cp_config['auth.require'].extend(conditions)
        return f
    return decorate

def load_user(username):
    '''returns a previously saved User object given a username'''
    userpath = os.path.join(user_dir, username + ".yaml")

    #first make sure the user exists
    if not os.path.exists(userpath): return False

    user = yaml.load(open(userpath, "r"))
    return user

def get_user():
    '''gets the User object for the current session-- from a saved file'''
    #note: cherrypy.session[SESSION_KEY] already has the User object,
    #but it could have changed since this session was last used,
    #so only use it to get the username of the user and get fresh data while you're at it.
    
    #assume that the user already exists
    username = cherrypy.session[SESSION_KEY].username

    #open up the user from the users/ directory
    user = load_user(username)
    return user

def is_username_available(username):
    file_path = os.path.join(user_dir, username + ".yaml")
    return not os.path.exists(file_path)

class User(yaml.YAMLObject):
    yaml_tag="!user"
    def __init__(self, username, password, email):
        if username:
            if is_username_available(username): raise ValueError, "User.__init__: a user with that name already exists"
            if password:
                if email:
                    assert is_valid_email(email), "User.__init__: email address must be valid"
                    self.username, self.password, self.email = username, md5(password).hexdigest(), email
                else: raise ValueError, "User.__init__: must be given an email address"
            else: raise ValueError, "User.__init__: must be given a password"
        else: raise ValueError, "User.__init__: must be given a username"
        self.save()
    def __eq__(self, other):
        if isinstance(other, User):
            if other.username == self.username: return True
            else: return False
        elif isinstance(other, str):
            if other==self.username: return True
            else: return False
        return False
    def save(self):
        '''saves self as yaml in a file somewhere based off of the username'''
        fh = open(os.path.join(user_dir, self.username + ".yaml"), "w")
        fh.write(yaml.dump(self))
        fh.close()

#conditions are callables that return True if the user fulfills the conditions they define, False otherwise
#access the current username as cherrypy.request.login

def member_of(*conditions):
    return True

def name_is(reqd_username):
    return lambda: reqd_username == cherrypy.request.login

def any_of(*conditions):
    '''returns true if any of the conditions match'''
    def check():
        for c in conditions:
            if c():
                return True
        return False
    return check

#by default all conditions are required, but this might still be
#needed if you want to use it inside of an any_of(...) condition
def all_of(*conditions):
    '''returns True if all of the conditions match'''
    def check():
        for c in conditions:
            if not c():
                return False
        return True
    return check

#controller to provide login and logout actions
class AuthController(object):
    def on_login(self, username):
        '''called on successful login'''
    def on_logout(self, username): #does anyone ever really use this on a site?
        '''called on logout'''
    def get_loginform(self, username, msg="Enter login information", from_page="/", **keywords):
        return """<form method="post" action="/auth/login">
            <input type="hidden" name="from_page" value="%(from_page)s" />
            %(msg)s<br />
            username: <input type="text" name="username" value="%(username)s" /><br />
            password: <input type="password" name="password" /><br />
            <input type="submit" value="Log in" />
            </form>""" % locals()
    @cherrypy.expose
    def login(self, username=None, password=None, from_page="/", **keywords):
        if username is None or password is None:
            return self.get_loginform("", from_page=from_page)

        success = check_credentials(username, password)
        if not success:
            return self.get_loginform(username, "username or password incorrect.", from_page)
        else:
            cherrypy.session[SESSION_KEY] = cherrypy.request.login = load_user(username)
            self.on_login(username)
            raise cherrypy.HTTPRedirect(from_page or "/")
    @cherrypy.expose
    def logout(self, from_page="/"):
        sess = cherrypy.session
        user = sess.get(SESSION_KEY, None)
        sess[SESSION_KEY] = None
        if user:
            cherrypy.request.login = None
            self.on_logout(user)
        raise cherrypy.HTTPRedirect(from_page or "/")

#so you can see how to 'hide' a page from unregistered/unloggedin users
class DemoRestrictedArea:
    '''all methods in this controller are available only to members named 'xyz'
    just a demo'''
    _cp_config = {
        'auth.require': [name_is("xyz")]
        }
    
    @cherrypy.expose
    def index(self):
        return "your username must be xyz to see this."

#######################################################################
#                   basic git/dulwich functionality
#######################################################################

def update_refspec(repo, commit, refspec):
    '''side effect on repo; updates a certain refspec to point to this commit'''
    if isinstance(commit, Commit):
        commit = commit.id
    repo.refs['refs/head/' + refspec] = commit

def update_master(repo, commit):
    #repo.refs['refs/head/master'] = commit.id
    update_refspec(repo, commit, "master")

def set_head(repo, refspec="master"):
    '''sets the head to a given refspec'''
    repo.refs["HEAD"] = "ref: refs/heads/" + refspec

def get_all_commits(repo_path="/home/kanzure/code/skdb/", commit= "a" * 40):
    repo = dulwich.repo.Repo(repo_path)
    store = repo.object_store.generate_pack_contents([], [commit])
    generator = store.iterobjects()
    commits = []
    for each in generator:
        commits.append(each)
    return commits

def extract_trees(repo, commit="a9b19e9453e516d7528aebb05a1efd66a0cd9347"):
    '''get a list of all known trees from a repo based on a commit SHA'''
    store = repo.object_store.generate_pack_contents([], [commit])
    generator = store.iterobjects()
    trees = []
    for each in generator:
        if isinstance(each, dulwich.objects.Tree):
            trees.append(each)
    return trees

def get_latest_tree(repo, refspec="HEAD"):
    """return the last known tree"""
    commit_id = repo.get_refs()[refspec]
    commit = repo.commit(commit_id)
    tree_id = commit.tree
    return repo.tree(tree_id)

def make_commit(repo, tree, message, author, timezone, encoding="UTF-8"):
    """build a Commit object"""
    commit = Commit()
    try:
        commit.parents = [repo.head()]
    except KeyError:
        #the initial commit has no parent
        pass
    if isinstance(tree, dulwich.objects.Tree): tree_id = tree.id
    elif isinstance(tree, str): tree_id = tree
    commit.tree = tree_id
    commit.message = message
    commit.author = commit.committer = author
    commit.commit_time = commit.author_time = int(time())
    commit.commit_timezone = commit.author_timezone = parse_timezone(timezone)
    commit.encoding = encoding
    return commit

def dictionary_updater(original, additions):
    '''suppose original = {"first": {"second": 1, "another": 3}}
    and additions = {"first": {"yet another": 59421}}
    .. the result should be:
    {"first": {"second": 1, "another": 3, "yet another": 59421}}'''
    return_value = copy(original)
    for key in additions.keys():
        if key not in original.keys():
            return_value[key] = additions[key]
        elif key in original.keys():
            if not isinstance(original[key], dict): return_value[key] = additions[key]
            else: #recursion time :)
                return_value[key] = dictionary_updater(original[key], additions[key])
    return return_value

def reassemble_index_into_dictionary(files):
    return_value = {}
    for file in files:
        path = file[0]
        sha = file[1][8]

        #split the path up
        path_parts = path.split("/")
        if len(path_parts)>0:
            #some/path/goes/here -- return_value["some"]["part"]["goes"]["here"]
            temp = sha 
            for bit in reversed(path_parts): temp = {bit: copy(temp)}
            return_value = dictionary_updater(return_value, temp)
    return return_value

def get_blob_contents(obj, repo=None):
    if isinstance(obj, str) and repo: obj = repo.get_object(sha)
    return obj.as_pretty_string()

#######################################################################
#                   core site functionality
#######################################################################

class ManagedPath:
    '''a url is parsed into a ManagedPath. the format is as follows:

    /home/some/page/new/ -->
                             parts = ["home", "some", "page", "new"]
                             cmd = "new"
                             path = ["home", "some", "page"]
    /x/y/z/new/1/2/3     -->
                             parts = ["x", "y", "z", "new", "1", "2", "3"]
                             cmd = "new"
                             path = ["x", "y", "z"]
    
    in "default" methods, this helps send the user somewhere.
    useful for a wiki.
    '''
    reserved_roots = ["account", "admin"] #for /account stuff.
    reserved_words = ["new", "delete", "edit", "history", "source", "archive"]
    def __init__(self, url=str()):
        self._parts = []
        self._cmd = ""
        self._path = []
        self._sha = None
        if isinstance(url, ManagedPath):
            for (k,v) in url.__dict__: setattr(self, k, copy(v))
        elif isinstance(url, str):
            self._url = url
            self.parse(url)
        elif isinstance(url, tuple):
            self._path = url
            self._url = join(url, "/")
            self.parse(self._url)
    def parse(self, url):
        self._url = url
        self._sha = ""
        if url.count("/") == 0: self._parts = []
        else:
            parts = url.split("/")
            if parts[0] in self.reserved_roots:
                self._cmd = parts[0]
                #now grab the sha
                if len(parts)>0:
                    if len(parts[1])==40 and parts[1].isalnum():
                        self._sha = parts[1]
            else:
                path = []
                i = 0
                for part in parts:
                    if part in self.reserved_words:
                        self._cmd = part
                        self._path = path
                        break
                    elif part is not "": path.append(part)
                    i = i+1
                if len(parts[-1])==40 and parts[-1].isalnum():
                    self._sha = parts[-1]
            self._parts = parts
    def __str__(self): return self._url
    def __repr__(self): return str(self)
    def __eq__(self, other):
        '''checks if the path is the same (not the parts)
        so /xyz/new/ matches /xyz/new/123'''
        if other._path == self._path: return True
        else: return False
    def get_path(self):
        if self._path is not []: return self._path
        self.parse(self._url)
        return self._path
    def get_cmd(self):
        if self._cmd is not "": return self._cmd
        self.parse(self._url)
        return self._cmd
    def get_sha(self):
        if self._sha is None: self.parse(self._url)
        return self._sha
    cmd=property(fget=get_cmd, doc="returns which command this url corresponds to")
    path=property(fget=get_path, doc="figures out the path on which the command should operate")
    sha=property(fget=get_sha, doc="returns the sha from the url")

class UnitApp:
    # def __init__(self):
    #     self._tmpl = IndexTemplate()
    def index(self, *extra, **keywords):
        if len(keywords)==2:
            first = skdb.Unit(keywords[keywords.keys()[0]])
            second = skdb.Unit(keywords[keywords.keys()[1]])
            return str(first.to(second))
        else: raise cherrypy.HTTPError(404, "try units/?one=50+m&two=km")
    index.exposed=True

class Uploader:
    '''simple file upload demo- doesn't really do much right now.'''
    def index(self):
        return """
        <html><body>
            <form action="upload" method="post" enctype="multipart/form-data">
            file: <input type="file" name="incoming_file" /><br />
            <input type="submit" />
            </form>
        </body></html>
        """
    index.exposed=True

    def upload(self, incoming_file):
        #get the goods
        handler = incoming_file.file
        contents = handler.read()
        
        #save the file
        #TODO: check if file already exists
        filename = incoming_file.filename
        target = open("templates/" + filename, "w")
        target.write(contents)
        target.close()

        #tell the user
        return "ok thanks, file has been uploaded"
    upload.exposed=True

class FileViewer: #(FileView): #eventually a template
    _cp_config = {
                    'request.error_response': handle_error,
                    'tools.sessions.on': True,
                    'tools.auth.on': True,
                 }
    acceptable_views = ["yaml", "html", "xml", "rss", "atom"]
    exposed=True
    def __init__(self, package, filename, extensions=True):
        self.package = package
        self.filename = filename
        self.extensions = extensions
    @cherrypy.expose
    def default(self, *virtual_path, **keywords):
        url = ManagedPath(virtual_path)
        if url.cmd == "edit": return self.edit
        if url.cmd == "" or not url.cmd:
            if len(virtual_path)>0:
                if len(virtual_path[0]) == 40:
                    cherrypy.request.params["branch"] = "master"
                    cherrypy.request.params["sha"] = virtual_path[0]
                    print "sha is: ", virtual_path[0]
                    return self.view_file(virtual_path, keywords)
        return str("FileViewer.default(virtual_path=%s, keywords=%s)" % (str(virtual_path), str(keywords)))
    @cherrypy.expose
    def view_file(self, *virtual_path, **keywords):
        branch = "master"
        desired_view = "default"
        sha = None
        if "sha" in keywords: sha = keywords["sha"]
        if "branch" in keywords: branch = keywords["branch"]
        if "desired_view" in keywords: desired_view = keywords["desired_view"]
        if self.package is None: raise cherrypy.NotFound()
        if not (desired_view in self.acceptable_views): raise cherrypy.NotFound()

        #create the dulwich.repo.Repo object
        repo = Repo(self.package.path())

        #switch to the right refspec
        set_head(repo, branch)
        
        #reconstruct the filename
        filename = self.filename + "." + desired_view #FIXME: this is a BAD hack

        #get the sha if it wasn't passed to us
        try:
            if not sha: sha = dulwich.object_store.tree_lookup_path(repo.get_object, repo.get_object(repo.head()).tree, filename)[1]
            print "sha is: ", sha
            obj = repo.get_object(sha)
        except IndexError: raise cherrypy.NotFound()

        return str(obj.as_pretty_string())
    @cherrypy.expose
    def edit(self, content=None, username=None, branch="master", id=None, *virtual_path, **keywords):
        '''id: the git id of the blob before it was edited'''
        url = ManagedPath(virtual_path)
        commit = virtual_path.sha
        if content==None and (id or branch):
            contents = self.file_handler.read()
            return_contents = "<form action=\"" + cherrypy.url() + "\" method=\"POST\">"
            return_contents = return_contents + "<textarea name=content rows='20' cols='120'>" + contents + "</textarea><br />"
            #if the user isn't logged in ...
            if not hasattr(cherrypy.session, "login"): return_contents = return_contents + "username: <input type=text name=username value=\"anonymous\"><br />"
            if id: return_contents = return_contents + "<input type=hidden name=id value=\"" + id + "\">"
            return_contents = return_contents + "<input type=hidden name=\"branch\" value=\"" + branch + "\">"
            return_contents = return_contents + "<input type=submit name=submit value=edit></form>"
            return return_contents
        elif (id or branch): #it's been edited
            if username==None and hasattr(cherrypy.session, "login"): 
                if cherrypy.session.login==None: raise ValueError, "FileViewer.edit: no username supplied"
            elif username==None:
                if SESSION_KEY in cherrypy.session.keys():
                    username = cherrypy.session[SESSION_KEY].username
                else: username = "anonymous"

                #TODO: implement
            
            return "edited (name=%s, branch=%s, id=%s)" % (username, branch, id)
    def __getattr__(self, name):
        if name == "__methods__" or name == "__members__": return
        if name in self.acceptable_views:
            cherrypy.request.params["desired_view"] = name
            return self.view_file
        raise AttributeError("%r object has no attribute %r" % (self.__class__.__name__, name))
        
class Package(PackageView, skdb.Package):
    _cp_config = {'request.error_response': handle_error}
    exposed=True
    package = None
    def __init__(self, package):
        PackageView.__init__(self)
        self.package = package
    @cherrypy.expose
    def index(self, **keywords):
        return ("individual package view for Package(" + str(self.package.name) + ")")
    @cherrypy.expose
    def default(self, *virtual_path, **keywords):
        if not virtual_path:
            return self.index(**keywords)
        url = ManagedPath(virtual_path)
        return_value = """Package.default(virtual_path=%s, keywords=%s)
        cmd is: %s
        virtual path is: %s
        """ % (str(virtual_path), str(keywords), url.cmd, url.path)
        return add_newlines(return_value)
    def __eq__(self, other):
        if isinstance(other, Package): #web package object
            if other.package == self.package: return True
            else: return False
        elif isinstance(other, skdb.Package): #skdb.Package object
            if self.package.name == other.name: return True
            else: return False
        elif isinstance(other, str): #package name
            if self.package.name == other: return True
            else: return False
        else: return False #dunno what to do
    def __getattr__(self, name):
        #could be a file object, attribute, or method of the package
        if name == "__methods__" or name == "__members__": return
        if self.package is not None:
            #FIXME: branches, SHAs, etc.
            if self.package.has_file(name,extensions=False): return FileViewer(package=self.package, filename=name, extensions=False)
        raise AttributeError("%r object has no attribute %r" % (self.__class__.__name__, name))

class PackageSet(PackageIndex):
    _cp_config = {'request.error_response': handle_error}
    _packages = []
    def __init__(self):
        PackageIndex.__init__(self)
    @cherrypy.expose
    def index(self, **keywords):
        return "PackageSet.index with keywords: " + str(list(keywords))
    @cherrypy.expose
    def default(self, *vpath, **keywords):
        #default view for a package
        return "PackageSet.default: vpath is: " + str(vpath)
    @classmethod
    def load_package(cls, name, branch="master"):
        #keep track of which branch we want
        cherrypy.request.params["branch"] = branch

        if not (name in cls._packages):
            if skdb.check_unix_name(name):
                new_package = skdb.Package(name=name, create=False)
                new_package_page = Package(new_package)
                cls._packages.append(new_package_page)
                return new_package_page
        else: #already in there
            return cls._packages[cls._packages.index(name)] #return the corresponding entry
    def __getattr__(self, name):
        if name == "__methods__" or name == "__members__": return
        if (not (name=="")) and not (name==None):
            branch = "master" #default branch is branch "master"
            if name.count(":") > 0:
                full_name = copy(name)
                name = full_name.split(":",1)[0]
                branch = full_name.split(":",1)[1]
            if skdb.check_unix_name(name): return self.load_package(name, branch=branch)
        raise AttributeError("%r object has no attribute %r" % (self.__class__.__name__, name))

class Root(IndexTemplate):
    _cp_config = {
        'request.error_response': handle_error,
        'tools.sessions.on': True,
        'tools.auth.on': True,
        }

    units = UnitApp() #simple example: /units/?one=m&two=km
    uploader = Uploader()
    package = PackageSet()
    auth = AuthController()

    def __init__(self):
        IndexTemplate.__init__(self)
    @cherrypy.expose
    def index(self, *extra, **keywords):
        return self.respond()
    @cherrypy.expose
    def default(self, *virtual_path, **keywords):
        if not virtual_path:
            return self.index(**keywords)
        url = ManagedPath(virtual_path)
        return_value = """
        Root.default(virtual_path=%s, keywords=%s)
        cmd is: %s
        virtual path is: %s
        """ % (str(virtual_path), str(keywords), url.cmd, url.path)
        return add_newlines(return_value)
    @cherrypy.expose
    @require(name_is("xyz"))
    def silly_protected_page_demo(self):
        return "your username must be 'xyz' in order to see this page."

#######################################################################
#              configuration and unit tests
#######################################################################

class SiteTest(helper.CPWebCase):
    def test_newliner(self):
        message="""put text here
        on to the next line"""
        result = add_newlines(message)
        self.assertTrue(result.count("<br />") == 1)
    def test_url(self):
        url1 = ManagedPath("/home/index/edit")
        self.assertTrue(url1.cmd == "edit")
        url2 = ManagedPath("/home/index/edit/")
        self.assertTrue(url2.cmd == "edit")
        
        url3 = ManagedPath("/home/index/edit/stuff/goes/here")
        self.assertTrue(url3.cmd == "edit")
        url4 = ManagedPath("/home/index/edit/stuff/goes/")
        self.assertTrue(url4.cmd == "edit")

        url5 = ManagedPath("/home/index/stuff/edit")
        self.assertTrue(url5.path == ["home", "index", "stuff"])
        url6 = ManagedPath("/path/to/the/file/new/extra/stuff/123")
        self.assertTrue(url6.path == ["path", "to", "the", "file"])
    def test_url_eq(self):
        url1 = ManagedPath("/home/index/edit/")
        url2 = ManagedPath("/home/index/edit/blah")
        self.assertTrue(url1 == url2)

        url3 = ManagedPath("/home/index/edit")
        self.assertTrue(url3 == url2)
    def test_sha_paths(self):
        url1 = ManagedPath("/path/to/the/file/edit/e19a9220403c381b1c86c23fc3532f1a7b7a18e1")
        self.assertTrue(url1.sha == "e19a9220403c381b1c86c23fc3532f1a7b7a18e1")
         
        url2 = ManagedPath("/path/to/the/file/e19a9220403c381b1c86c23fc3532f1a7b7a18e1")
        self.assertTrue(url2.sha == "e19a9220403c381b1c86c23fc3532f1a7b7a18e1")
    def test_package(self):
        self.getPage("/package/lego/", method="GET")
        #print self.body
        self.assertStatus(200) #see also assertBody

        self.getPage("/package/lego/data/", method="GET")
        #print self.body
        self.assertStatus(200)

        self.getPage("/package/lego/data/yaml", method="GET")
        print self.body
        self.assertStatus(200)

        #what about /package/lego/data/yaml/edit ?
    def test_email_addresses(self):
        self.assertTrue(is_valid_email("hello@me.com"))
        self.assertFalse(is_valid_email("user@user.1.2.3."))
    def test_branch_page_view(self):
        '''note: branches can only be one word with no slashes'''

        urls = [
                "/package/lego/data/yaml",
                "/package/lego;master/data/yaml",
                "/package/lego;another/data/yaml",
               ]

#url: http://projects.dowski.com/files/cp22collection/cp22collection.py?version=colorized
def setup_server():
    cherrypy.tree.mount(Root(), '/')
    cherrypy.config.update({
            'server.log_to_screen': False,
            'autoreload.on': False,
            'log_debug_info_filter.on': False,
            'environment': 'test_suite',
    })

def conf_maker(static_dir): #so i don't have to type static file config stuff a billion times
    return {
        "tools.staticdir.on": True,
        "tools.staticdir.index": "index.html",
        "tools.staticdir.dir": os.path.join(current_dir, static_dir),
    }

#url: http://www.cherrypy.org/wiki/StaticContent
current_dir = os.path.dirname(os.path.abspath(__file__))
conf = {
    "/favicon.ico": {
        "tools.staticfile.on": True,
        "tools.staticfile.filename": os.path.join(current_dir, os.path.join("images", "favicon.ico")),
        },
    }
conf["/styles"] = conf_maker("styles")
conf["/templates"] = conf_maker("templates")
conf["/javascripts"] = conf_maker("javascripts")
conf["/images"] = conf_maker("images")

cherrypy.tools.auth = cherrypy.Tool('before_handler', check_auth)
application = cherrypy.Application(Root(), script_name=None, config=conf)

if __name__ == "__main__":
    webtest.WebCase.interactive = False
    setup_server()
    helper.testmain()
