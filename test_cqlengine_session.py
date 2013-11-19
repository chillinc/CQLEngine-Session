from datetime import datetime
import unittest
import uuid

from cqlengine import columns
from cqlengine.connection import setup
from cqlengine.management import create_keyspace, delete_keyspace
from cqlengine.query import DoesNotExist
from cqlengine_session import AttributeUnavailable, clear, save, SessionModel

def groom_time(dtime):
    return datetime(*dtime.timetuple()[:6])

def now():
    return groom_time(datetime.now())

def make_todo_model():
    class Todo(SessionModel):
        uuid = columns.UUID(primary_key=True, default=uuid.uuid4)
        title = columns.Text(max_length=60)
        text = columns.Text()
        done = columns.Boolean()
        pub_date = columns.DateTime()

    return Todo

def make_no_default_todo_model():
    class Todo(SessionModel):
        uuid = columns.UUID(primary_key=True)
        title = columns.Text(max_length=60)
        text = columns.Text()
        done = columns.Boolean()
        pub_date = columns.DateTime()

    return Todo

def make_inherited_model():
    class IntermediateTodo(SessionModel):
        __abstract__ = True
        base_text = columns.Text()

    class Todo(IntermediateTodo):
        uuid = columns.UUID(primary_key=True, default=uuid.uuid4)
        title = columns.Text(max_length=60)
        text = columns.Text()
        done = columns.Boolean()
        pub_date = columns.DateTime()

    return Todo

def make_multi_key_model():
    class Todo(SessionModel):
        partition = columns.UUID(primary_key=True, default=uuid.uuid4)
        uuid = columns.UUID(primary_key=True, default=uuid.uuid4)
        title = columns.Text(max_length=60)
        text = columns.Text()
        done = columns.Boolean()
        pub_date = columns.DateTime(primary_key=True, default=now)

    return Todo

def make_no_default_multi_key_model():
    class Todo(SessionModel):
        partition = columns.UUID(primary_key=True)
        uuid = columns.UUID(primary_key=True)
        title = columns.Text(max_length=60)
        text = columns.Text()
        done = columns.Boolean()
        pub_date = columns.DateTime(primary_key=True)

    return Todo

def make_counter_model():
    class TestCounterModel(SessionModel):
        partition = columns.UUID(primary_key=True, default=uuid.uuid4)
        cluster = columns.UUID(primary_key=True, default=uuid.uuid4)
        counter = columns.Counter()

    return TestCounterModel

class BaseTestCase(unittest.TestCase):

    model_classes = {}

    def setUp(self):
        keyspace = 'testkeyspace{}'.format(str(uuid.uuid1()).replace('-', ''))
        self.keyspace = keyspace
        clear()
        # Configure cqlengine's global connection pool.
        setup('localhost:9160', default_keyspace=keyspace)
        create_keyspace(keyspace)
        for class_name, creator in self.model_classes.items():
            setattr(self, class_name, creator())
            #sync_table(getattr(self, class_name))
            getattr(self, class_name).sync_table()

    def tearDown(self):
        delete_keyspace(self.keyspace)

class BasicTestCase(BaseTestCase):

    model_classes = {'Todo': make_todo_model}

    def test_basic_insert(self):
        # create an object

        todo = self.Todo.create(title='first', text='text1')
        todo_key = todo.uuid
        print '----------------------------------------'
        print 'todo_key {}'.format(todo_key)
        self.assertTrue(isinstance(todo_key, uuid.UUID))
        self.assertEqual(todo.title, 'first')
        self.assertEqual(todo.text, 'text1')
        self.assertEqual(todo.done, None)
        self.assertEqual(todo.pub_date, None)

        # Do a non-session execute to confirm it's not there.
        # (not sure if this is defined behavior, as it should look up the
        # object in the session to begin with?  I think in this case it is
        # getting the object back from storage and then linking it with the
        # object in the identity map, so, fixing this is TODO, as this
        # way of checking was from the old way of handling the objects.)
        raised = None
        try:
            self.Todo.id_mapped_class.objects(uuid=todo_key).get()
        except Exception, e:
            raised = e
            self.assertTrue(isinstance(e, DoesNotExist))
        else:
            self.assertTrue(False)

        # save the session, and thus the object.
        save()

        # Confirm some identity map functionality.
        self.assertIs(todo, todo)
        found = self.Todo.objects(uuid=todo_key).get()
        self.assertIs(found, todo)

        # Clear the session
        clear()

        found = self.Todo.objects(uuid=todo_key).get()
        self.assertFalse(found is todo)

        self.assertEqual(found.title, 'first')
        self.assertEqual(found.text, 'text1')
        # xxx boolean seems to not like None, and insists on False.
        #self.assertEqual(found.done, None)
        self.assertEqual(found.pub_date, None)

    def test_basic_update(self):
        todo = self.Todo.create(title='first', text='text1')
        todo_key = todo.uuid
        old_todo = todo
        save()

        # Get a new session.
        clear()
        # Load the object into the session.
        todo = self.Todo.objects(uuid=todo_key).get()

        # confirm the session cleared.
        self.assertIsNot(todo, old_todo)

        # Set some values.
        todo.title = u'new title'
        todo.text = u'new text'
        todo.done = True
        todo.pub_date = now()

        # Confirm the local assignment.
        self.assertEqual(todo.uuid, todo_key)
        self.assertEqual(todo.title, u'new title')
        self.assertEqual(todo.text, u'new text')
        self.assertEqual(todo.done, True)

        save()

        # Confirm the object is readable after save.
        self.assertEqual(todo.uuid, todo_key)
        self.assertEqual(todo.title, u'new title')
        self.assertEqual(todo.text, u'new text')
        self.assertEqual(todo.done, True)

        old_todo = todo

        # Clear the session.
        clear()
        todo = self.Todo.objects(uuid=todo_key).get()
        # Confirm again the session is cleared.
        self.assertIsNot(todo, old_todo)
        self.assertEqual(todo.uuid, todo_key)
        self.assertEqual(todo.title, u'new title')
        self.assertEqual(todo.text, u'new text')
        self.assertEqual(todo.done, True)
        old_todo = todo

        # Test a blind update.
        clear()
        todo = self.Todo(todo_key)
        self.assertFalse(old_todo is todo)
        todo.title = u'new new title'
        self.assertEqual(todo.title, u'new new title')
        old_todo = todo
        save()

        clear()
        todo = self.Todo.objects(uuid=todo_key).get()
        self.assertFalse(old_todo is todo)
        self.assertEqual(todo.uuid, todo_key)
        self.assertEqual(todo.title, u'new new title')
        self.assertEqual(todo.text, u'new text')
        self.assertEqual(todo.done, True)

    def test_loaded_dirty_load(self):
        todo = self.Todo.create(title='first', text='text1')
        todo_key = todo.uuid
        todo.title = u'new title'
        todo.text = u'new text'
        todo.done = True
        todo.pub_date = now()
        save()

        # Get a new session.
        clear()
        # Load the object into the session.
        todo = self.Todo.objects(uuid=todo_key).get()

        self.assertEqual(todo.uuid, todo_key)
        self.assertEqual(todo.title, u'new title')
        self.assertEqual(todo.text, u'new text')
        self.assertEqual(todo.done, True)

        # Change a value.
        todo.title = u'new new title'
        # And load again, the load should not clobber the local change.
        todo = self.Todo.objects(uuid=todo_key).get()
        self.assertEqual(todo.title, u'new new title')
        save()
        clear()
        todo = self.Todo.objects(uuid=todo_key).get()
        self.assertEqual(todo.title, u'new new title')

    def test_blind_dirty_load(self):
        todo = self.Todo.create(title='first', text='text1')
        todo_key = todo.uuid
        todo.title = u'new title'
        todo.text = u'new text'
        todo.done = True
        todo.pub_date = now()
        save()

        # Get a new session.
        clear()
        # Get a blind handle to the object.
        todo = self.Todo(todo_key)
        # Change a value.
        todo.title = u'new new title'
        # Load. the load should not clobber the local change.
        load_todo = self.Todo.objects(uuid=todo_key).get()
        self.assertTrue(todo is load_todo)
        self.assertEqual(todo.title, u'new new title')
        save()
        clear()
        todo = self.Todo.objects(uuid=todo_key).get()
        self.assertEqual(todo.title, u'new new title')

    def test_multi_result_load(self):
        todo1 = self.Todo.create(title='first', text='text1')
        todo2 = self.Todo.create(title='second', text='text2')
        todo3 = self.Todo.create(title='third', text='text3')
        todo4 = self.Todo.create(title='fourth', text='text4')
        todo5 = self.Todo.create(title='fifth', text='text5')
        save()

        results = self.Todo.all()
        self.assertEqual(5, len(results))
        results = set(results)
        self.assertIn(todo1, results)
        self.assertIn(todo2, results)
        self.assertIn(todo3, results)
        self.assertIn(todo4, results)
        self.assertIn(todo5, results)

        todo1_key = todo1.uuid
        todo2_key = todo2.uuid
        todo3_key = todo3.uuid
        todo4_key = todo4.uuid
        todo5_key = todo5.uuid
        clear()

        results = self.Todo.all()
        self.assertEqual(5, len(results))
        keys = set([t.uuid for t in results])
        self.assertIn(todo1_key, keys)
        self.assertIn(todo2_key, keys)
        self.assertIn(todo3_key, keys)
        self.assertIn(todo4_key, keys)
        self.assertIn(todo5_key, keys)

    def test_missing_attributes(self):
        todo = self.Todo.create(title='first', text='text1')
        todo_key = todo.uuid
        todo.title = u'title'
        todo.text = u'text'
        todo.done = True
        todo.pub_date = now()
        save()

        # Get a new session.
        clear()

        # Get a blind handle to the object.
        todo = self.Todo(todo_key)
        self.assertRaises(AttributeUnavailable, getattr, todo, 'title')
        # Load the data to this object.
        todo.get()
        self.assertEqual(todo.title, u'title')

    def test_blind_set_to_none(self):
        todo = self.Todo.create(title='first', text='text1')
        todo_key = todo.uuid
        todo.title = u'title'
        todo.text = u'text'
        todo.done = True
        todo.pub_date = now()
        save()

        # Get a new session.
        clear()

        # Get a blind handle to the object.
        todo = self.Todo(todo_key)
        todo.title = None
        save()
        clear()

        todo = self.Todo.objects(uuid=todo_key).get()
        assert todo.title == None


class NoDefaultTestCase(BaseTestCase):

    model_classes = {'Todo': make_no_default_todo_model}

    def test_basic_insert(self):

        self.assertRaises(ValueError, self.Todo.create, title='first', text='text1')

class NoDefaultTestCase(BaseTestCase):

    model_classes = {'Todo': make_no_default_todo_model}

    def test_basic_insert(self):
        with self.assertRaises(ValueError):
            self.Todo.create(title='first', text='text1')

        self.Todo.create(uuid=uuid.uuid4())

class NoDefaultMultiTestCase(BaseTestCase):

    model_classes = {'Todo': make_no_default_multi_key_model}

    def test_basic_insert(self):
        with self.assertRaises(ValueError):
            self.Todo.create(title='first', text='text1')

        self.Todo.create(partition=uuid.uuid4(),
                         uuid=uuid.uuid4(),
                         pub_date=now())


class InheritedTestCase(BaseTestCase):

    model_classes = {'Todo': make_inherited_model}

    def test_basic(self):
        todo = self.Todo.create()
        todo.title = u'parent title'
        todo.base_text = u'base text'
        save()
        clear()
        todo = self.Todo.get()
        assert todo.title == u'parent title'
        assert todo.base_text == u'base text'

class MultiKeyTestCase(BaseTestCase):

    model_classes = {'Todo': make_multi_key_model}

    def test_basic(self):
        todo = self.Todo.create()
        todo.title = u'multitest'
        partition = todo.partition
        cluster1 = todo.uuid
        cluster2 = todo.pub_date
        save()
        clear()

        todo = self.Todo.objects(partition=partition, uuid=cluster1, pub_date=cluster2).get()
        assert todo.title == u'multitest'

        print '-------calling create---------'
        new_cluster2 = groom_time(datetime(2013, 11, 15, 16, 12, 10))
        todo2 = self.Todo.create(partition=partition, uuid=cluster1, pub_date=new_cluster2)
        self.assertIsNot(todo2, todo)
        save()

        print '-------making new instance w same stuff'
        todo3 = self.Todo(partition, cluster1, new_cluster2)
        self.assertIs(todo2, todo3)

        print '-----calling get-----'
        todo4 = self.Todo.objects(partition=partition,
                                  uuid=cluster1,
                                  pub_date=new_cluster2).get()
        assert todo4.pub_date == new_cluster2
        self.assertIs(todo2, todo4)

class IntrospectionTestCase(BaseTestCase):

    model_classes = {'Todo': make_todo_model,
                     'MultiTodo': make_multi_key_model,
                     'Counter': make_counter_model}

    def test_class_vars(self):
        assert self.Todo.uuid
        assert self.Todo.title
        assert self.Todo.text
        assert self.Todo.done
        assert self.Todo.pub_date
        assert not self.Todo._has_counter
        assert 1 == len(self.Todo._primary_keys)
        assert self.Todo._primary_keys['uuid'] == self.Todo.uuid

        assert self.MultiTodo.uuid
        assert self.MultiTodo.title
        assert self.MultiTodo.text
        assert self.MultiTodo.done
        assert self.MultiTodo.pub_date
        assert not self.MultiTodo._has_counter
        assert 3 == len(self.MultiTodo._primary_keys)
        assert [('partition', self.MultiTodo.partition),
                ('uuid', self.MultiTodo.uuid),
                ('pub_date', self.MultiTodo.pub_date)] == list(self.MultiTodo._primary_keys.iteritems())

        assert self.Counter.partition
        assert self.Counter.cluster
        assert self.Counter.counter
        assert self.Counter._has_counter
        assert 2 == len(self.Counter._primary_keys)
        assert [('partition', self.Counter.partition),
                ('cluster', self.Counter.cluster)] == list(self.Counter._primary_keys.iteritems())


