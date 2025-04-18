from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import reverse
from wagtail.models import Collection, GroupCollectionPermission
from wagtail.test.utils import WagtailTestUtils

from wagtailmedia import models


class TestMediaPermissions(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Create some user accounts for testing permissions
        User = get_user_model()
        cls.user = User.objects.create_user(
            username="user", email="user@email.com", password="password"
        )
        cls.owner = User.objects.create_user(
            username="owner", email="owner@email.com", password="password"
        )
        cls.editor = User.objects.create_user(
            username="editor", email="editor@email.com", password="password"
        )
        cls.editor.groups.add(Group.objects.get(name="Editors"))
        cls.administrator = User.objects.create_superuser(
            username="administrator",
            email="administrator@email.com",
            password="password",
        )

        # Owner user must have the add_media permission
        cls.adders_group = Group.objects.create(name="Media adders")
        GroupCollectionPermission.objects.create(
            group=cls.adders_group,
            collection=Collection.get_first_root_node(),
            permission=Permission.objects.get(codename="add_media"),
        )
        cls.owner.groups.add(cls.adders_group)

        # Create a media for running tests on
        cls.media = models.Media.objects.create(
            title="Test media", duration=100, uploaded_by_user=cls.owner
        )

    def test_administrator_can_edit(self):
        self.assertTrue(self.media.is_editable_by_user(self.administrator))

    def test_editor_can_edit(self):
        self.assertTrue(self.media.is_editable_by_user(self.editor))

    def test_owner_can_edit(self):
        self.assertTrue(self.media.is_editable_by_user(self.owner))

    def test_user_cant_edit(self):
        self.assertFalse(self.media.is_editable_by_user(self.user))


class TestEditOnlyPermissions(TestCase, WagtailTestUtils):
    @classmethod
    def setUpTestData(cls):
        cls.root_collection = Collection.get_first_root_node()
        cls.evil_plans_collection = cls.root_collection.add_child(name="Evil plans")
        cls.nice_plans_collection = cls.root_collection.add_child(name="Nice plans")

        # Create a media to edit
        cls.media = models.Media.objects.create(
            title="Test media",
            file=ContentFile("A boring example song", name="song.mp3"),
            collection=cls.nice_plans_collection,
            duration=100,
        )

        # Create a user with change_media permission but not add_media
        cls.user = get_user_model().objects.create_user(
            username="changeonly", email="changeonly@example.com", password="password"
        )
        change_permission = Permission.objects.get(
            content_type__app_label="wagtailmedia", codename="change_media"
        )
        admin_permission = Permission.objects.get(
            content_type__app_label="wagtailadmin", codename="access_admin"
        )
        cls.changers_group = Group.objects.create(name="Media changers")
        GroupCollectionPermission.objects.create(
            group=cls.changers_group,
            collection=cls.root_collection,
            permission=change_permission,
        )
        cls.user.groups.add(cls.changers_group)

        cls.user.user_permissions.add(admin_permission)

        cls.collection_label_tag = '<label class="w-field__label" for="id_collection" id="id_collection-label">'

    def setUp(self):
        self.client.force_login(self.user)

    def test_get_index(self):
        response = self.client.get(reverse("wagtailmedia:index"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "wagtailmedia/media/index.html")

        # user should not get an "Add audio" and "Add video" buttons
        self.assertNotContains(response, "Add audio")
        self.assertNotContains(response, "Add video")

        # user should be able to see media not owned by them
        self.assertContains(response, "Test media")

    def test_search(self):
        response = self.client.get(reverse("wagtailmedia:index"), {"q": "Hello"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["query_string"], "Hello")

    def test_get_add(self):
        response = self.client.get(reverse("wagtailmedia:add", args=("audio",)))
        # permission should be denied
        self.assertRedirects(response, reverse("wagtailadmin_home"))

    def test_get_edit(self):
        response = self.client.get(reverse("wagtailmedia:edit", args=(self.media.id,)))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "wagtailmedia/media/edit.html")

        # media can only be moved to collections you have add permission for,
        # so the 'collection' field is not available here
        self.assertNotContains(response, self.collection_label_tag)

        # if the user has add permission on a different collection,
        # they should have option to move the media
        add_permission = Permission.objects.get(
            content_type__app_label="wagtailmedia", codename="add_media"
        )
        GroupCollectionPermission.objects.create(
            group=self.changers_group,
            collection=self.evil_plans_collection,
            permission=add_permission,
        )
        response = self.client.get(reverse("wagtailmedia:edit", args=(self.media.id,)))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.collection_label_tag)
        self.assertContains(response, "Nice plans")
        self.assertContains(response, "Evil plans")

    def test_post_edit(self):
        # Submit title change
        response = self.client.post(
            reverse("wagtailmedia:edit", args=(self.media.id,)),
            {
                "title": "Test media changed!",
                "file": "",
                "duration": 100,
            },
        )

        # User should be redirected back to the index
        self.assertRedirects(response, reverse("wagtailmedia:index"))

        # Media title should be changed
        self.assertEqual(
            models.Media.objects.get(id=self.media.id).title, "Test media changed!"
        )

        # collection should be unchanged
        self.assertEqual(
            models.Media.objects.get(id=self.media.id).collection,
            self.nice_plans_collection,
        )

        # if the user has add permission on a different collection,
        # they should have option to move the media
        add_permission = Permission.objects.get(
            content_type__app_label="wagtailmedia", codename="add_media"
        )
        GroupCollectionPermission.objects.create(
            group=self.changers_group,
            collection=self.evil_plans_collection,
            permission=add_permission,
        )

        self.client.post(
            reverse("wagtailmedia:edit", args=(self.media.id,)),
            {
                "title": "Test media changed!",
                "collection": self.evil_plans_collection.id,
                "file": "",
                "duration": 100,
            },
        )
        self.assertEqual(
            models.Media.objects.get(id=self.media.id).collection,
            self.evil_plans_collection,
        )

    def test_get_delete(self):
        response = self.client.get(
            reverse("wagtailmedia:delete", args=(self.media.id,))
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "wagtailmedia/media/confirm_delete.html")
