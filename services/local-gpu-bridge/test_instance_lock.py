import pathlib,subprocess,sys,tempfile,unittest


class InstanceTests(unittest.TestCase):
    def test_second_process_rejected_and_lock_released_on_exit(self):
        source = str(pathlib.Path(__file__).parent)
        script = "import sys;sys.path.insert(0,sys.argv[1]);from bridge import acquire_instance_lock;lock=acquire_instance_lock(sys.argv[2]);print('locked',flush=True);sys.stdin.readline()"
        with tempfile.TemporaryDirectory() as tmp:
            first = subprocess.Popen([sys.executable, '-u', '-c', script, source, tmp],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                self.assertEqual(first.stdout.readline().strip(), 'locked')
                second = subprocess.run([sys.executable, '-c', script, source, tmp],
                                        input='\n', capture_output=True, text=True, timeout=10)
                self.assertNotEqual(second.returncode, 0)
                self.assertIn('already running', second.stderr)
            finally:
                first.communicate('\n', timeout=10)
            third = subprocess.run([sys.executable, '-c', script, source, tmp],
                                   input='\n', capture_output=True, text=True, timeout=10)
            self.assertEqual(third.returncode, 0, third.stderr)


if __name__ == '__main__':
    unittest.main()
