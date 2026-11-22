from django.test import SimpleTestCase, override_settings


@override_settings(USE_TZ=True)
class TestCase(SimpleTestCase):
    pass
