import json
import logging
import warnings
import pytz

from datetime import datetime, timedelta

from lxml import etree

from xblock.core import XBlock
from xblock.fields import Integer, Scope, Boolean
from xblock.fragment import Fragment
from pkg_resources import resource_string

from .exceptions import NotFoundError
from .fields import Date
from .mako_module import MakoModuleDescriptor
from .progress import Progress
from .x_module import XModule, STUDENT_VIEW
from .xml_module import XmlDescriptor

log = logging.getLogger(__name__)

# HACK: This shouldn't be hard-coded to two types
# OBSOLETE: This obsoletes 'type'
class_priority = ['video', 'problem']

# Make '_' a no-op so we can scrape strings
_ = lambda text: text


class SequenceFields(object):
    has_children = True

    # NOTE: Position is 1-indexed.  This is silly, but there are now student
    # positions saved on prod, so it's not easy to fix.
    position = Integer(help="Last tab viewed in this sequence", scope=Scope.user_state)
    due = Date(
        display_name=_("Due Date"),
        help=_("Enter the date by which problems are due."),
        scope=Scope.settings,
    )

    # Entrance Exam flag -- see cms/contentstore/views/entrance_exam.py for usage
    is_entrance_exam = Boolean(
        display_name=_("Is Entrance Exam"),
        help=_(
            "Tag this course module as an Entrance Exam. "
            "Note, you must enable Entrance Exams for this course setting to take effect."
        ),
        default=False,
        scope=Scope.content,
    )

    is_time_limited = Boolean(
        display_name=_("Is Time Limited"),
        help=_(
            "This setting indicates whether students have a limited time"
            " to view or interact with this courseware component."
        ),
        default=False,
        scope=Scope.settings,
    )

    default_time_limit_mins = Integer(
        display_name=_("Time Limit in Minutes"),
        help=_(
            "The number of minutes available to users for viewing or interacting with this courseware component."
        ),
        default=None,
        scope=Scope.settings,
    )

    time_student_started = Date(
        display_name=_("Time Student Started"),
        help=_("The time at which the student began interacting with the time limited content."),
        default=None,
        scope=Scope.user_state,  # pylint: disable=no-member
    )

    student_time_limit_mins = Integer(
        display_name=_("Student Time Limit in Minutes"),
        help=_(
            "The number of minutes available to this student for viewing or interacting with this courseware component."
            " If specified, this time limit overrides the default time limit. "
            "(Is this correct? is a particular student specified somehow?)"
        ),
        default=None,
        scope=Scope.user_state,  # pylint: disable=no-member
    )

    is_proctored_enabled = Boolean(
        display_name=_("Is Proctoring Enabled"),
        help=_(
            "This setting indicates whether this exam is a proctored exam."
        ),
        default=False,
        scope=Scope.settings,
    )


@XBlock.wants('proctoring')
@XBlock.wants('user')
class SequenceModule(SequenceFields, XModule):
    ''' Layout module which lays out content in a temporal sequence
    '''
    js = {
        'coffee': [resource_string(__name__, 'js/src/sequence/display.coffee')],
        'js': [resource_string(__name__, 'js/src/sequence/display/jquery.sequence.js')],
    }
    css = {
        'scss': [resource_string(__name__, 'css/sequence/display.scss')],
    }
    js_module_name = "Sequence"

    def __init__(self, *args, **kwargs):
        super(SequenceModule, self).__init__(*args, **kwargs)

        # If position is specified in system, then use that instead.
        position = getattr(self.system, 'position', None)
        if position is not None:
            try:
                self.position = int(self.system.position)
            except (ValueError, TypeError):
                # Check for https://openedx.atlassian.net/browse/LMS-6496
                warnings.warn(
                    "Sequential position cannot be converted to an integer: {pos!r}".format(
                        pos=self.system.position,
                    ),
                    RuntimeWarning,
                )

    def get_progress(self):
        ''' Return the total progress, adding total done and total available.
        (assumes that each submodule uses the same "units" for progress.)
        '''
        # TODO: Cache progress or children array?
        children = self.get_children()
        progresses = [child.get_progress() for child in children]
        progress = reduce(Progress.add_counts, progresses, None)
        return progress

    def handle_ajax(self, dispatch, data):  # TODO: bounds checking
        ''' get = request.POST instance '''
        if dispatch == 'goto_position':
            # set position to default value if either 'position' argument not
            # found in request or it is a non-positive integer
            position = data.get('position', u'1')
            if position.isdigit() and int(position) > 0:
                self.position = int(position)
            else:
                self.position = 1
            return json.dumps({'success': True})
        elif dispatch == 'start_gated_exam':
            # callback when user chooses to enter into a gated
            # (e.g. timed or proctored exam)

            proctoring_service = self.runtime.service(self, 'proctoring')
            user_service = self.runtime.service(self, 'user')
            user_id = user_service.get_current_user().opt_attrs['edx-platform.user_id']
            course_id = self.runtime.course_id
            location = self.location
            exam = proctoring_service.get_exam_by_content_id(course_id, location)
            exam_id = exam['id']

            self.runtime.service(self, 'proctoring').start_exam_attempt(exam_id, user_id, None)

            return json.dumps({'success': True})
        raise NotFoundError('Unexpected dispatch type')

    def _get_proctoring_context(self):
        """
        Interface with the proctoring subsystem to get
        information about the students state with respect
        to timed examinations/proctoring
        """
        has_started_exam = False
        has_finished_exam = False
        has_time_expired = False

        if self.is_time_limited:
            proctoring_service = self.runtime.service(self, 'proctoring')
            user_service = self.runtime.service(self, 'user')
            user_id = user_service.get_current_user().opt_attrs['edx-platform.user_id']
            course_id = self.runtime.course_id
            location = self.location
            if proctoring_service and user_service:
                user_attempt = None
                exam_id = None
                try:
                    exam = proctoring_service.get_exam_by_content_id(course_id, location)
                    exam_id = exam['id']
                except:
                    exam_id = proctoring_service.create_exam(
                        course_id=course_id,
                        content_id=unicode(location),
                        exam_name=self.display_name,
                        time_limit_mins=self.default_time_limit_mins
                    )

                attempt = proctoring_service.get_exam_attempt(exam_id, user_id)
                has_started_exam = attempt is not None
                if attempt:
                    now_utc = datetime.now(pytz.UTC)
                    expires_at = attempt['started_at'] + timedelta(minutes=self.default_time_limit_mins)
                    has_time_expired = now_utc > expires_at

        context = {
            'in_timed_exam': self.is_time_limited,
            'in_proctored_exam': self.is_proctored_enabled,
            'has_started_exam': has_started_exam,
            'has_finished_exam': has_finished_exam,
            'has_time_expired': has_time_expired
        }

        print '***** context = {}'.format(context)

        return context

    def student_view(self, context):
        # If we're rendering this sequence, but no position is set yet,
        # default the position to the first element
        if self.position is None:
            self.position = 1

        context = context if context else {}
        context.update({
            'proctoring_context': self._get_proctoring_context()
        })

        ## Returns a set of all types of all sub-children
        contents = []

        fragment = Fragment()

        for child in self.get_display_items():
            progress = child.get_progress()
            rendered_child = child.render(STUDENT_VIEW, context)
            fragment.add_frag_resources(rendered_child)

            titles = child.get_content_titles()
            childinfo = {
                'content': rendered_child.content,
                'title': "\n".join(titles),
                'page_title': titles[0] if titles else '',
                'progress_status': Progress.to_js_status_str(progress),
                'progress_detail': Progress.to_js_detail_str(progress),
                'type': child.get_icon_class(),
                'id': child.scope_ids.usage_id.to_deprecated_string(),
            }
            if childinfo['title'] == '':
                childinfo['title'] = child.display_name_with_default
            contents.append(childinfo)

        params = {'items': contents,
                  'element_id': self.location.html_id(),
                  'item_id': self.location.to_deprecated_string(),
                  'position': self.position,
                  'tag': self.location.category,
                  'ajax_url': self.system.ajax_url,
                  'proctoring_context': context['proctoring_context']
                  }

        fragment.add_content(self.system.render_template('seq_module.html', params))

        return fragment

    def get_icon_class(self):
        child_classes = set(child.get_icon_class()
                            for child in self.get_children())
        new_class = 'other'
        for c in class_priority:
            if c in child_classes:
                new_class = c
        return new_class


class SequenceDescriptor(SequenceFields, MakoModuleDescriptor, XmlDescriptor):
    mako_template = 'widgets/sequence-edit.html'
    module_class = SequenceModule

    show_in_read_only_mode = True

    js = {
        'coffee': [resource_string(__name__, 'js/src/sequence/edit.coffee')],
    }
    js_module_name = "SequenceDescriptor"

    @classmethod
    def definition_from_xml(cls, xml_object, system):
        children = []
        for child in xml_object:
            try:
                child_block = system.process_xml(etree.tostring(child, encoding='unicode'))
                children.append(child_block.scope_ids.usage_id)
            except Exception as e:
                log.exception("Unable to load child when parsing Sequence. Continuing...")
                if system.error_tracker is not None:
                    system.error_tracker(u"ERROR: {0}".format(e))
                continue
        return {}, children

    def definition_to_xml(self, resource_fs):
        xml_object = etree.Element('sequential')
        for child in self.get_children():
            self.runtime.add_block_as_child_node(child, xml_object)
        return xml_object

    @property
    def non_editable_metadata_fields(self):
        """
        `is_entrance_exam` should not be editable in the Studio settings editor.
        """
        non_editable_fields = super(SequenceDescriptor, self).non_editable_metadata_fields
        non_editable_fields.append(self.fields['is_entrance_exam'])
        return non_editable_fields

    def index_dictionary(self):
        """
        Return dictionary prepared with module content and type for indexing.
        """
        # return key/value fields in a Python dict object
        # values may be numeric / string or dict
        # default implementation is an empty dict
        xblock_body = super(SequenceDescriptor, self).index_dictionary()
        html_body = {
            "display_name": self.display_name,
        }
        if "content" in xblock_body:
            xblock_body["content"].update(html_body)
        else:
            xblock_body["content"] = html_body
        xblock_body["content_type"] = "Sequence"

        return xblock_body
