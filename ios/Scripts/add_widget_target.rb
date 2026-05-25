#!/usr/bin/env ruby
# Adds the WHVWidgets widget extension target to WHV.xcodeproj.
#
# Idempotent — re-running is a no-op once the target exists. Uses
# CocoaPods' xcodeproj gem for safe pbxproj editing rather than
# hand-patching the file.
#
# Run:  cd ios && ruby Scripts/add_widget_target.rb
#
# What this configures (matching what `File > New > Target > Widget
# Extension` does in Xcode 16):
#  * New PBXNativeTarget WHVWidgets, productType app-extension,
#    bundle id com.wagner-hausverwaltung.WHV.WHVWidgets
#  * Sources phase that pulls in WHVWidgets/*.swift
#  * Resources phase for the Info.plist
#  * Frameworks phase linking SwiftUI + WidgetKit (auto via
#    @main + import statements; we just leave the phase empty)
#  * Embed App Extensions copy phase on the WHV app target that
#    copies the widget .appex into PlugIns/
#  * Both targets get CODE_SIGN_ENTITLEMENTS pointing at their
#    respective .entitlements files (App Group plumbing)
#  * Target dependency: WHV -> WHVWidgets

require 'xcodeproj'

PROJ_PATH = File.expand_path(File.join(__dir__, '..', 'WHV.xcodeproj'))
WIDGET_TARGET_NAME = 'WHVWidgets'
APP_TARGET_NAME = 'WHV'
WIDGET_BUNDLE_ID = 'com.wagner-hausverwaltung.WHV.WHVWidgets'
APP_BUNDLE_ID = 'com.wagner-hausverwaltung.WHV'
WIDGET_FOLDER = 'WHVWidgets'
WIDGET_ENTITLEMENTS = 'WHVWidgets/WHVWidgets.entitlements'
APP_ENTITLEMENTS = 'WHV/WHV.entitlements'

project = Xcodeproj::Project.open(PROJ_PATH)

app_target = project.targets.find { |t| t.name == APP_TARGET_NAME }
abort("Could not find WHV target") unless app_target

# Shared sources (visible to both targets). Loops at the end so
# re-runs converge regardless of which targets pre-existed.
SHARED_FILES = ['Shared/ETVActivity.swift'].freeze

def ensure_shared_file(project, app_target, widget_target, relative_path)
  # Find or create the file ref under a "Shared" group at root.
  shared_group = project.main_group.find_subpath('Shared', true)
  shared_group.set_source_tree('<group>')
  shared_group.path ||= 'Shared'
  filename = File.basename(relative_path)
  file_ref = shared_group.files.find { |f| f.path == filename }
  file_ref ||= shared_group.new_reference(filename)

  [app_target, widget_target].compact.each do |target|
    next if target.source_build_phase.files_references.include?(file_ref)
    target.source_build_phase.add_file_reference(file_ref)
  end
end

if project.targets.any? { |t| t.name == WIDGET_TARGET_NAME }
  puts "WHVWidgets target already exists — backfilling PRODUCT_NAME, NSSupportsLiveActivities, shared sources, and new widget files …"
  widget_target = project.targets.find { |t| t.name == WIDGET_TARGET_NAME }
  widget_target.build_configurations.each do |config|
    config.build_settings['PRODUCT_NAME'] ||= '$(TARGET_NAME)'
  end
  # NSSupportsLiveActivities lives on the HOST app, not the widget.
  app_target.build_configurations.each do |config|
    config.build_settings['INFOPLIST_KEY_NSSupportsLiveActivities'] = 'YES'
  end
  SHARED_FILES.each do |rel|
    ensure_shared_file(project, app_target, widget_target, rel)
  end

  # Re-scan WHVWidgets/*.swift so files dropped in after the target
  # was first created (e.g. ETVLiveActivity, RunningLateIntent)
  # actually land in the build phase. Same pattern PBXFileSystem-
  # SynchronizedRootGroup gives the app target for free.
  widget_group = project.main_group.find_subpath(WIDGET_TARGET_NAME, false)
  if widget_group
    Dir.glob(File.join(__dir__, '..', WIDGET_FOLDER, '*.swift')).sort.each do |path|
      filename = File.basename(path)
      file_ref = widget_group.files.find { |f| f.path == filename }
      file_ref ||= widget_group.new_reference(filename)
      unless widget_target.source_build_phase.files_references.include?(file_ref)
        widget_target.source_build_phase.add_file_reference(file_ref)
      end
    end
  end

  project.save
  puts "✓ Settings + shared sources + widget files updated."
else
  puts "Adding WHVWidgets target …"

  # Group containing widget sources. Plain PBXGroup (not the
  # synchronized variant) because we want explicit control over
  # which files land in the widget vs. the app.
  widget_group = project.main_group.new_group(WIDGET_TARGET_NAME, WIDGET_FOLDER)

  widget_sources = []
  Dir.glob(File.join(__dir__, '..', WIDGET_FOLDER, '*.swift')).sort.each do |path|
    relative = File.basename(path)
    file_ref = widget_group.new_reference(relative)
    widget_sources << file_ref
  end

  info_plist_ref = widget_group.new_reference('Info.plist')
  entitlements_ref = widget_group.new_reference('WHVWidgets.entitlements')

  widget_target = project.new_target(
    :app_extension,
    WIDGET_TARGET_NAME,
    :ios,
    '17.0'
  )

  # Source files.
  widget_sources.each do |ref|
    widget_target.source_build_phase.add_file_reference(ref)
  end

  # Build settings — bundle id, entitlements, dev team, signing,
  # plist location. Mirrors what `Targets > WHVWidgets > Signing &
  # Capabilities` would set via the UI.
  widget_target.build_configurations.each do |config|
    settings = config.build_settings
    settings['PRODUCT_NAME'] = '$(TARGET_NAME)'
    settings['PRODUCT_BUNDLE_IDENTIFIER'] = WIDGET_BUNDLE_ID
    settings['INFOPLIST_FILE'] = 'WHVWidgets/Info.plist'
    settings['CODE_SIGN_ENTITLEMENTS'] = WIDGET_ENTITLEMENTS
    settings['CODE_SIGN_STYLE'] = 'Automatic'
    settings['DEVELOPMENT_TEAM'] = '5XQDFG9H83'
    settings['SWIFT_VERSION'] = '5.0'
    settings['IPHONEOS_DEPLOYMENT_TARGET'] = '17.0'
    settings['TARGETED_DEVICE_FAMILY'] = '1,2'
    settings['SKIP_INSTALL'] = 'YES'
    settings['LD_RUNPATH_SEARCH_PATHS'] = [
      '$(inherited)',
      '@executable_path/Frameworks',
      '@executable_path/../../Frameworks',
    ]
    # Generate the standard widget Info.plist keys via
    # INFOPLIST_FILE; no GENERATE_INFOPLIST_FILE because we ship
    # our own plist (Info.plist contains only the WidgetKit
    # extension point).
    settings['GENERATE_INFOPLIST_FILE'] = 'NO'
    settings['INFOPLIST_KEY_CFBundleDisplayName'] = 'WHV ETV-Widget'
    settings['MARKETING_VERSION'] = '0.1.0'
    settings['CURRENT_PROJECT_VERSION'] = '1'
  end

  # Embed the widget .appex into the app's PlugIns folder so the
  # widget binary ships inside WHV.app.
  embed_phase = app_target.build_phases.find do |p|
    p.is_a?(Xcodeproj::Project::Object::PBXCopyFilesBuildPhase) &&
      p.symbol_dst_subfolder_spec == :plug_ins
  end
  embed_phase ||= app_target.new_copy_files_build_phase('Embed App Extensions')
  embed_phase.symbol_dst_subfolder_spec = :plug_ins
  embed_phase.name = 'Embed App Extensions'
  unless embed_phase.files_references.include?(widget_target.product_reference)
    build_file = embed_phase.add_file_reference(widget_target.product_reference)
    build_file.settings = { 'ATTRIBUTES' => ['RemoveHeadersOnCopy'] }
  end

  # App target depends on widget so it builds before the embed.
  app_target.add_dependency(widget_target)

  # App-side entitlements (App Group) — only set if not already
  # pointing at a different file the developer manually configured.
  app_target.build_configurations.each do |config|
    existing = config.build_settings['CODE_SIGN_ENTITLEMENTS']
    if existing.nil? || existing.empty?
      config.build_settings['CODE_SIGN_ENTITLEMENTS'] = APP_ENTITLEMENTS
    end
  end

  project.save
  puts "✓ Added WHVWidgets target, embed phase, and entitlements wiring."
end
