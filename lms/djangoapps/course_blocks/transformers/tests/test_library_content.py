"""
Tests for ContentLibraryTransformer.
"""
import mock
from student.tests.factories import UserFactory
from student.tests.factories import CourseEnrollmentFactory

from course_blocks.transformers.library_content import ContentLibraryTransformer
from course_blocks.api import get_course_blocks, clear_course_from_cache
from lms.djangoapps.course_blocks.transformers.tests.test_helpers import CourseStructureTestCase


class MockedModules(object):
    """
    Object with mocked selected modules for user.
    """
    def __init__(self, state):
        """
        Set state attribute on initialize.
        """
        self.state = state


class ContentLibraryTransformerTestCase(CourseStructureTestCase):
    """
    ContentLibraryTransformer Test
    """

    def setUp(self):
        """
        Setup course structure and create user for content library transformer test.
        """
        super(ContentLibraryTransformerTestCase, self).setUp()

        # Build course.
        self.course_hierarchy = self.get_test_course_hierarchy()
        self.blocks = self.build_course(self.course_hierarchy)
        self.course = self.blocks['course']
        clear_course_from_cache(self.course.id)

        # Set up user and enroll in course.
        self.password = 'test'
        self.user = UserFactory.create(password=self.password)
        CourseEnrollmentFactory.create(user=self.user, course_id=self.course.id, is_active=True)

        self.selected_modules = [MockedModules('{"selected": [["vertical", "vertical_vertical2"]]}')]
        self.transformer = []

    def get_test_course_hierarchy(self):
        """
        Get a course hierarchy to test with.
        """
        return {
            'org': 'ContentLibraryTransformer',
            'course': 'CL101F',
            'run': 'test_run',
            '#ref': 'course',
            '#children': [
                {
                    '#type': 'chapter',
                    '#ref': 'chapter1',
                    '#children': [
                        {
                            '#type': 'sequential',
                            '#ref': 'lesson1',
                            '#children': [
                                {
                                    '#type': 'vertical',
                                    '#ref': 'vertical1',
                                    '#children': [
                                        {
                                            'metadata': {'category': 'library_content'},
                                            '#type': 'library_content',
                                            '#ref': 'library_content1',
                                            '#children': [
                                                {
                                                    'metadata': {'display_name': "CL Vertical 1"},
                                                    '#type': 'vertical',
                                                    '#ref': 'vertical2',
                                                    '#children': [
                                                        {
                                                            'metadata': {'display_name': "HTML1"},
                                                            '#type': 'html',
                                                            '#ref': 'html1',
                                                        }
                                                    ]
                                                },
                                                {
                                                    'metadata': {'display_name': "CL Vertical 2"},
                                                    '#type': 'vertical',
                                                    '#ref': 'vertical3',
                                                    '#children': [
                                                        {
                                                            'metadata': {'display_name': "HTML2"},
                                                            '#type': 'html',
                                                            '#ref': 'html2',
                                                        }
                                                    ]
                                                }
                                            ]
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ]
        }

    def test_course_structure_with_user_course_library(self):
        """
        Test course structure integrity if course has content library section.
        First test user can't see any content library section,
        and after that mock response from MySQL db.
        Check user can see mocked sections in content library.
        """
        self.transformer = ContentLibraryTransformer()

        raw_block_structure = get_course_blocks(
            self.user,
            self.course.location,
            transformers={}
        )
        self.assertEqual(len(list(raw_block_structure.get_block_keys())), len(self.blocks))

        clear_course_from_cache(self.course.id)
        trans_block_structure = get_course_blocks(
            self.user,
            self.course.location,
            transformers={self.transformer}
        )

        self.assertEqual(
            set(trans_block_structure.get_block_keys()),
            self.get_block_key_set('course', 'chapter1', 'lesson1', 'vertical1', 'library_content1')
        )

        # Check course structure again, with mocked selected modules for a user.
        with mock.patch(
            'course_blocks.transformers.library_content.ContentLibraryTransformer._get_selected_modules',
            return_value=self.selected_modules
        ):
            clear_course_from_cache(self.course.id)
            trans_block_structure = get_course_blocks(
                self.user,
                self.course.location,
                transformers={self.transformer}
            )
            self.assertEqual(
                set(trans_block_structure.get_block_keys()),
                self.get_block_key_set(
                    'course',
                    'chapter1',
                    'lesson1',
                    'vertical1',
                    'library_content1',
                    'vertical2',
                    'html1'
                )
            )
