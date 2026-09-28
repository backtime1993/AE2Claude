import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from tools import configure_startup as startup


class StartupPreferencesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.main = self.root/'Adobe After Effects 27.0 Prefs.txt'
        self.debug = self.root/'Debug Database.txt'
        self.main.write_bytes(b'["General Section"]\r\n\t"Show Welcome Screen" = 01\r\n["Other"]\r\n"Preserve" = 01\r\n')
        self.debug.write_bytes(b'AEDebugDatabaseVersion\t2\t0\r\nAE.DebugShowPreviousCrashWarning\ttrue\ttrue\r\r\nOther\tfalse\ttrue\r\n')

    def test_apply_is_exact_backed_up_and_idempotent(self):
        before = [p.read_bytes() for p in (self.main,self.debug)]
        result = startup.apply(startup.plan(self.root,False,False),self.root/'backups')
        self.assertEqual(result['changed'],2)
        self.assertEqual(self.main.read_bytes(),before[0].replace(b'Screen" = 01',b'Screen" = 00'))
        self.assertEqual(self.debug.read_bytes(),before[1].replace(b'Warning\ttrue\ttrue',b'Warning\tfalse\ttrue'))
        for p,data in zip((self.main,self.debug),before):
            self.assertEqual((Path(result['backup'])/p.name).read_bytes(),data)
        self.assertEqual(startup.apply(startup.plan(self.root,False,False),self.root/'backups')['changed'],0)

    def test_missing_version_specific_key_rejects_all_changes(self):
        before = self.main.read_bytes()
        self.debug.write_bytes(b'Unrelated\ttrue\ttrue\r\n')
        with self.assertRaisesRegex(ValueError,'Unsupported'):
            startup.plan(self.root,False,False)
        self.assertEqual(self.main.read_bytes(),before)

    def test_existing_debug_database_in_separate_major_directory(self):
        other=self.root/'major25'
        other.mkdir()
        separated=other/'Debug Database.txt'
        self.debug.rename(separated)
        rows=startup.plan(self.root,False,False,separated)
        result=startup.apply(rows,self.root/'backups')
        self.assertEqual(result['changed'],2)
        self.assertFalse((self.root/'Debug Database.txt').exists())
        self.assertEqual([r['current'] for r in startup.plan(self.root,None,None,separated)],[False,False])
        self.assertTrue((Path(result['backup'])/'Debug Database.txt').is_file())

    def test_second_write_failure_restores_first_file(self):
        before=self.main.read_bytes()
        real_write=startup.atomic_write
        def fail_second(path,data):
            if path==self.debug:
                raise OSError('test replacement failure')
            return real_write(path,data)
        with patch.object(startup,'atomic_write',side_effect=fail_second):
            with self.assertRaises(OSError):
                startup.apply(startup.plan(self.root,False,False),self.root/'backups')
        self.assertEqual(self.main.read_bytes(),before)


if __name__=='__main__':
    unittest.main()
