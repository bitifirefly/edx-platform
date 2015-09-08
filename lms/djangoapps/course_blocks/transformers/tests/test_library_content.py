"""
Tests for ContentLibraryTransformation.
"""
from openedx.core.djangoapps.user_api.partition_schemes import RandomUserPartitionScheme
from opaque_keys.edx.keys import CourseKey
from student.tests.factories import UserFactory
from student.tests.factories import CourseEnrollmentFactory
from xmodule.modulestore.django import modulestore
from xmodule.partitions.partitions import Group, UserPartition

from course_blocks.transformers.library_content import ContentLibraryTransformer
from course_blocks.api import get_course_blocks, clear_course_from_cache
from test_helpers import CourseStructureTestCase

from course_blocks.transformers.helpers import get_user_partition_groups


class ContentLibraryTransformerTestCase(CourseStructureTestCase):
    """
    ...
    """

    def setUp(self):
        super(ContentLibraryTransformerTestCase, self).setUp()

        # Set up user partitions and groups.
        self.groups = [Group(3, 'Group A'), Group(4, 'Group B')]
        self.content_groups = [3, 4]
        self.split_test_user_partition = UserPartition(
            id=0,
            name='Partition 2',
            description='This is partition 2',
            groups=self.groups,
            scheme=RandomUserPartitionScheme
        )
        self.split_test_user_partition.scheme.name = "random"

        # Build course.
        self.course_hierarchy = self.get_test_course_hierarchy()
        self.blocks = self.build_course(self.course_hierarchy)
        self.course = self.blocks['course']
        clear_course_from_cache(self.course.id)

        # Set up user and enroll in course.
        self.password = 'test'
        self.user = UserFactory.create(password=self.password)
        CourseEnrollmentFactory.create(user=self.user, course_id=self.course.id, is_active=True)

    def get_test_course_hierarchy(self):
        """
        Get a course hierarchy to test with.

        Assumes self.user_partition has already been initialized.
        """
        return {
            'org': 'ContentLibraryTransformer',
            'course': 'ST101F',
            'run': 'test_run',
            'user_partitions': [self.split_test_user_partition],
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
                                            'metadata': {'category': 'split_test'}, 
                                            'user_partition_id': 0,
                                            'group_id_to_child': {
                                                "3": "i4x://SplitTestTransformation/ST101F/vertical/vertical_vertical2",
                                                "4": "i4x://SplitTestTransformation/ST101F/vertical/vertical_vertical3"
                                            },
                                            '#type': 'split_test',
                                            '#ref': 'split_test1',
                                            '#children': [
                                                {
                                                    'metadata': {'display_name': "Group ID 3"},
                                                    '#type': 'vertical',
                                                    '#ref': 'vertical2',
                                                    '#children': [
                                                        {
                                                            'metadata': {'display_name': "Group A"},
                                                            '#type': 'html',
                                                            '#ref': 'html1',
                                                        }
                                                    ]
                                                }, 
                                                {
                                                    'metadata': {'display_name': "Group ID 4"},
                                                    '#type': 'vertical',
                                                    '#ref': 'vertical3',
                                                    '#children': [
                                                        {
                                                            'metadata': {'display_name': "Group A"},
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

    def add_user_to_splittest_group(self, assign=True):
        """
        Add user to split test, get group for him and update blocks.
        """
        self.split_test_user_partition.scheme.get_group_for_user(
            CourseKey.from_string(unicode(self.course.id)),
            self.user,
            self.split_test_user_partition,
            assign=assign,
        )
        store = modulestore()
        for __, block in self.blocks.iteritems():
            block.save()
            store.update_item(block, self.user.id)

    def get_block_key_set(self, *refs):
        """
        Gets the set of usage keys that correspond to the list of
        #ref values as defined on self.blocks.

        Returns: set[UsageKey]
        """
        xblocks = (self.blocks[ref] for ref in refs)
        return set([xblock.location for xblock in xblocks])

    def test_course_structure_with_user_split_test(self):
        self.transformation = SplitTestTransformation()

        # Add user to split test.
        self.add_user_to_splittest_group(assign=False)

        __, raw_data_blocks = get_course_blocks(
            self.user,
            self.course.id,
            transformations={}
        )
        self.assertEqual(len(raw_data_blocks), len(self.blocks))

        clear_course_from_cache(self.course.id)
        __, trans_data_blocks = get_course_blocks(
            self.user,
            self.course.id,
            transformations={self.transformation}
        )

        user_groups = get_user_partition_groups(
            self.course.id, [self.split_test_user_partition], self.user
        )

        self.assertEqual(
            set(trans_data_blocks.keys()),
            self.get_block_key_set('course', 'chapter1', 'lesson1', 'vertical1', 'split_test1')
        )

    def test_course_structure_with_user_split_test_group_assigned(self):
        self.transformation = SplitTestTransformation()

        # Add user to split test.
        self.add_user_to_splittest_group()

        __, raw_data_blocks = get_course_blocks(
            self.user,
            self.course.id,
            transformations={}
        )
        self.assertEqual(len(raw_data_blocks), len(self.blocks))

        clear_course_from_cache(self.course.id)
        __, trans_data_blocks = get_course_blocks(
            self.user,
            self.course.id,
            transformations={self.transformation}
        )

        user_groups = get_user_partition_groups(
            self.course.id, [self.split_test_user_partition], self.user
        )
        for group in user_groups.itervalues():
            if group.id == 3:
                self.assertEqual(
                    set(trans_data_blocks.keys()),
                    self.get_block_key_set('course', 'chapter1', 'lesson1', 'vertical1', 'split_test1', 'vertical2', 'html1')
                )
            else:
                self.assertEqual(
                    set(trans_data_blocks.keys()),
                    self.get_block_key_set('course', 'chapter1', 'lesson1', 'vertical1', 'split_test1', 'vertical3', 'html2')
                )
